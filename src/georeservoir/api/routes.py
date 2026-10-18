"""Versioned endpoints. Each calculation endpoint calls exactly one core function and
returns its CalculationRecord unchanged (wrapped with api_version and project_id).

No endpoint accepts a filesystem path or executable content; files arrive only as
uploads, are written to a private temporary directory and deleted after parsing.
"""

import inspect
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from georeservoir import __version__
from georeservoir.api import schemas as s
from georeservoir.api.config import Scope, Settings
from georeservoir.api.security import CalcSlots, Principal
from georeservoir.common.exceptions import InputValidationError
from georeservoir.common.record import CalculationRecord
from georeservoir.engineering import (
    bourdet,
    dca,
    material_balance,
    nodal,
    petrophysics,
    uncertainty,
    well_path,
)

T = TypeVar("T")
PREFIX = "/api/v1/projects/{project_id}"
#: Explicit descriptions: the default HTTP reason phrases differ between Python versions
#: (e.g. 413 "Request Entity Too Large" vs "Content Too Large"), which would make the
#: committed OpenAPI contract depend on the interpreter.
_ERROR_TEXT: dict[int, str] = {
    401: "Missing or invalid API key",
    403: "Project or scope not allowed for this key",
    413: "Request body or uploaded file above the server limit",
    422: "Invalid request or scientific input error (typed)",
    429: "Rate limit exceeded (see Retry-After)",
    501: "Feature planned (maturity M0), not implemented",
    503: "All calculation slots busy (see Retry-After)",
    504: "Calculation exceeded the server timeout",
}
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": s.ErrorResponse, "description": text} for code, text in _ERROR_TEXT.items()
}
_MATURITY = re.compile(r"Maturity:\s*(M[0-3])")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _settings(request: Request) -> Settings:
    st: Settings = request.app.state.settings
    return st


def _principal(scope: Scope) -> Callable[..., Principal]:
    """Authentication, rate limiting and authorisation happen in GuardMiddleware before
    the body is read; this dependency re-checks that the request was authorised for this
    project and scope (defence in depth) and exposes the principal to the handler."""

    def dep(request: Request, project_id: str) -> Principal:
        auth = getattr(request.state, "authorized", None)
        if not auth or auth[1] != project_id or auth[2] != scope:
            raise HTTPException(status_code=403, detail="not allowed for this project")
        return Principal(auth[0], project_id)

    return dep


CalcAuth = Annotated[Principal, Depends(_principal("calc"))]
UploadAuth = Annotated[Principal, Depends(_principal("upload"))]


def _check_lengths(model: BaseModel, limit: int, prefix: str = "") -> None:
    for name, value in model:
        if isinstance(value, list) and len(value) > limit:
            raise InputValidationError(
                f"{prefix}{name}: {len(value)} elements; this server accepts at most {limit}"
            )
        if isinstance(value, BaseModel):
            _check_lengths(value, limit, f"{prefix}{name}.")


async def _run(request: Request, fn: Callable[[], T]) -> T:
    st = _settings(request)
    slots: CalcSlots = request.app.state.calc_slots
    return await slots.run(
        fn, queue_timeout_s=st.queue_timeout_s, calc_timeout_s=st.calc_timeout_s
    )


def _envelope(principal: Principal, rec: CalculationRecord) -> dict[str, Any]:
    return {"api_version": "v1", "project_id": principal.project_id, "record": rec.to_dict()}


def _doc(fn: Callable[..., Any]) -> str:
    """Docstring normalised the same way on every Python version (3.13 dedents)."""
    return inspect.cleandoc(fn.__doc__ or "")


def _maturity(fn: Callable[..., Any]) -> str:
    m = _MATURITY.search(fn.__doc__ or "")
    return m.group(1) if m else "unknown"


def _calc(
    app: FastAPI,
    path: str,
    model: type[s.Req],
    core: Callable[..., Any],
    build: Callable[[Any], Callable[[], CalculationRecord]],
    tag: str,
    reference: str,
) -> None:
    """Register POST {PREFIX}/calc/{path} taking ``model`` and calling ``core``."""

    async def endpoint(request: Request, principal: CalcAuth, body: model) -> dict[str, Any]:  # type: ignore[valid-type]
        _check_lengths(body, _settings(request).max_array_len)
        rec = await _run(request, build(body))
        return _envelope(principal, rec)

    endpoint.__name__ = "calc_" + path.replace("/", "_").replace("-", "_")
    app.post(
        f"{PREFIX}/calc/{path}",
        response_model=s.CalcResponse,
        tags=[tag],
        responses=ERRORS,
        summary=_doc(core).splitlines()[0],
        description=_doc(core),
    )(endpoint)
    app.state.methods.append(
        s.MethodInfo(
            endpoint=f"POST {PREFIX}/calc/{path}",
            method=f"{core.__module__}.{core.__qualname__}",
            maturity=_maturity(core),
            reference=reference,
        )
    )


def _dist(d: Any) -> uncertainty.Distribution:
    if d.kind == "fixed":
        return uncertainty.Fixed(d.value)
    if d.kind == "uniform":
        return uncertainty.Uniform(d.low, d.high)
    if d.kind == "triangular":
        return uncertainty.Triangular(d.low, d.mode, d.high)
    if d.kind == "normal":
        return uncertainty.Normal(d.mean, d.sd, d.low, d.high)
    return uncertainty.LogNormal(d.median, d.sigma_ln)


def _ipr(b: s.IprReq) -> nodal.IPRModel:
    def need(name: str, v: float | None) -> float:
        if v is None:
            raise InputValidationError(f"ipr.{name}: required for model {b.model!r}")
        return v

    if b.model == "linear":
        return nodal.LinearIPR(b.p_res, need("j", b.j))
    if b.model == "vogel":
        return nodal.VogelIPR(b.p_res, need("q_max", b.q_max))
    return nodal.CompositeIPR(b.p_res, need("p_bubble", b.p_bubble), need("j", b.j))


def _ipr_call(b: s.IprReq) -> CalculationRecord:
    if b.model == "linear":
        if b.j is None:
            raise InputValidationError("j: required for model 'linear'")
        return nodal.ipr_linear(b.pwf, p_res=b.p_res, j=b.j, pressure_unit=b.pressure_unit)
    if b.model == "vogel":
        if b.q_max is None:
            raise InputValidationError("q_max: required for model 'vogel'")
        return nodal.ipr_vogel(b.pwf, p_res=b.p_res, q_max=b.q_max, pressure_unit=b.pressure_unit)
    if b.j is None or b.p_bubble is None:
        raise InputValidationError("j and p_bubble: required for model 'composite'")
    return nodal.ipr_composite(
        b.pwf, p_res=b.p_res, p_bubble=b.p_bubble, j=b.j, pressure_unit=b.pressure_unit
    )


VSH: dict[str, Callable[..., CalculationRecord]] = {
    "larionov_tertiary": petrophysics.vsh_larionov_tertiary,
    "larionov_older": petrophysics.vsh_larionov_older,
    "steiber": petrophysics.vsh_steiber,
    "clavier": petrophysics.vsh_clavier,
}


def register(app: FastAPI) -> None:
    methods_list: list[s.MethodInfo] = []
    app.state.methods = methods_list

    @app.get("/api/v1/health", response_model=s.HealthResponse, tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness check (no authentication; returns no data)."""
        return {"status": "ok", "api_version": "v1", "library_version": __version__}

    @app.get(
        f"{PREFIX}/methods", response_model=list[s.MethodInfo], tags=["meta"], responses=ERRORS
    )
    async def methods(request: Request, principal: CalcAuth) -> list[s.MethodInfo]:
        """Available calculations with their maturity level and reference."""
        return list(request.app.state.methods)

    # ---- well path
    _calc(
        app,
        "well-path/minimum-curvature",
        s.MinimumCurvatureReq,
        well_path.minimum_curvature,
        lambda b: (
            lambda: well_path.minimum_curvature(
                b.md,
                b.inclination_deg,
                b.azimuth_deg,
                length_unit=b.length_unit,
                azimuth_reference=b.azimuth_reference,
                start_east=b.start_east,
                start_north=b.start_north,
                start_tvd=b.start_tvd,
            )
        ),
        "well path",
        well_path.METHOD_REF,
    )

    # ---- petrophysics
    _calc(
        app,
        "petrophysics/gamma-ray-index",
        s.GammaRayIndexReq,
        petrophysics.gamma_ray_index,
        lambda b: (
            lambda: petrophysics.gamma_ray_index(
                b.gr_api, gr_min_api=b.gr_min_api, gr_max_api=b.gr_max_api, clip=b.clip
            )
        ),
        "petrophysics",
        petrophysics.REF_IGR,
    )
    _calc(
        app,
        "petrophysics/vsh",
        s.VshReq,
        petrophysics.vsh_steiber,
        lambda b: lambda: VSH[b.method](b.igr),
        "petrophysics",
        "Larionov (1969); Steiber (1970); Clavier et al. (1971) — see method",
    )
    _calc(
        app,
        "petrophysics/density-porosity",
        s.DensityPorosityReq,
        petrophysics.density_porosity,
        lambda b: (
            lambda: petrophysics.density_porosity(
                b.rho_bulk_g_cc,
                rho_matrix_g_cc=b.rho_matrix_g_cc,
                rho_fluid_g_cc=b.rho_fluid_g_cc,
                clip=b.clip,
            )
        ),
        "petrophysics",
        petrophysics.REF_DENSITY,
    )
    _calc(
        app,
        "petrophysics/sonic-porosity-wyllie",
        s.SonicPorosityReq,
        petrophysics.sonic_porosity_wyllie,
        lambda b: (
            lambda: petrophysics.sonic_porosity_wyllie(
                b.dt_us_per_ft,
                dt_matrix_us_per_ft=b.dt_matrix_us_per_ft,
                dt_fluid_us_per_ft=b.dt_fluid_us_per_ft,
                clip=b.clip,
            )
        ),
        "petrophysics",
        petrophysics.REF_WYLLIE,
    )
    _calc(
        app,
        "petrophysics/archie-sw",
        s.ArchieSwReq,
        petrophysics.archie_water_saturation,
        lambda b: (
            lambda: petrophysics.archie_water_saturation(
                b.porosity, b.rt_ohm_m, rw_ohm_m=b.rw_ohm_m, a=b.a, m=b.m, n=b.n, clip=b.clip
            )
        ),
        "petrophysics",
        petrophysics.REF_ARCHIE,
    )
    _calc(
        app,
        "petrophysics/archie-rt",
        s.ArchieRtReq,
        petrophysics.archie_true_resistivity,
        lambda b: (
            lambda: petrophysics.archie_true_resistivity(
                b.porosity, b.sw, rw_ohm_m=b.rw_ohm_m, a=b.a, m=b.m, n=b.n
            )
        ),
        "petrophysics",
        petrophysics.REF_ARCHIE,
    )

    # ---- DCA
    _calc(
        app,
        "dca/rate",
        s.ArpsReq,
        dca.arps_rate,
        lambda b: (
            lambda: dca.arps_rate(
                b.t, qi=b.qi, di=b.di, b=b.b, time_unit=b.time_unit, d_terminal=b.d_terminal
            )
        ),
        "dca",
        dca.REF_ARPS,
    )
    _calc(
        app,
        "dca/cumulative",
        s.ArpsReq,
        dca.arps_cumulative,
        lambda b: (
            lambda: dca.arps_cumulative(
                b.t, qi=b.qi, di=b.di, b=b.b, time_unit=b.time_unit, d_terminal=b.d_terminal
            )
        ),
        "dca",
        dca.REF_ARPS,
    )
    _calc(
        app,
        "dca/eur",
        s.ArpsEurReq,
        dca.arps_eur,
        lambda b: (
            lambda: dca.arps_eur(
                qi=b.qi,
                di=b.di,
                b=b.b,
                time_unit=b.time_unit,
                d_terminal=b.d_terminal,
                q_limit=b.q_limit,
                t_horizon=b.t_horizon,
            )
        ),
        "dca",
        dca.REF_ARPS,
    )
    _calc(
        app,
        "dca/fit",
        s.ArpsFitReq,
        dca.arps_fit,
        lambda b: (
            lambda: dca.arps_fit(b.t, b.q, include=_bool_array(b.include), time_unit=b.time_unit)
        ),
        "dca",
        dca.REF_ARPS,
    )
    _calc(
        app,
        "dca/nominal-to-effective",
        s.DeclineConversionReq,
        dca.nominal_to_effective_decline,
        lambda b: lambda: dca.nominal_to_effective_decline(b.values, b=b.b),
        "dca",
        dca.REF_SPEE,
    )
    _calc(
        app,
        "dca/effective-to-nominal",
        s.DeclineConversionReq,
        dca.effective_to_nominal_decline,
        lambda b: lambda: dca.effective_to_nominal_decline(b.values, b=b.b),
        "dca",
        dca.REF_SPEE,
    )

    # ---- nodal
    _calc(
        app,
        "nodal/ipr",
        s.IprReq,
        nodal.ipr_vogel,
        lambda b: lambda: _ipr_call(b),
        "nodal",
        f"{nodal.REF_LINEAR}; {nodal.REF_VOGEL}; {nodal.REF_COMPOSITE}",
    )
    _calc(
        app,
        "nodal/vogel-qmax-from-test",
        s.VogelQmaxReq,
        nodal.vogel_qmax_from_test,
        lambda b: (
            lambda: nodal.vogel_qmax_from_test(
                p_res=b.p_res, q_test=b.q_test, pwf_test=b.pwf_test, pressure_unit=b.pressure_unit
            )
        ),
        "nodal",
        nodal.REF_VOGEL,
    )
    _calc(
        app,
        "nodal/composite-j-from-test",
        s.CompositeJReq,
        nodal.composite_j_from_test,
        lambda b: (
            lambda: nodal.composite_j_from_test(
                p_res=b.p_res,
                p_bubble=b.p_bubble,
                q_test=b.q_test,
                pwf_test=b.pwf_test,
                pressure_unit=b.pressure_unit,
            )
        ),
        "nodal",
        nodal.REF_COMPOSITE,
    )
    _calc(
        app,
        "nodal/solve",
        s.NodalSolveReq,
        nodal.nodal_solve,
        lambda b: (
            lambda: nodal.nodal_solve(
                _ipr(b.ipr),
                nodal.TabulatedTPR(b.tpr_q, b.tpr_pwf),
                pressure_unit=b.ipr.pressure_unit,
                n_grid=b.n_grid,
                xtol=b.xtol,
                maxiter=b.maxiter,
            )
        ),
        "nodal",
        nodal.REF_NODAL,
    )

    # ---- Bourdet
    _calc(
        app,
        "bourdet/derivative",
        s.BourdetReq,
        bourdet.bourdet_derivative,
        lambda b: (
            lambda: bourdet.bourdet_derivative(
                b.dt, b.dp, window_ln=b.window_ln, sigma_p=b.sigma_p, pressure_unit=b.pressure_unit
            )
        ),
        "well test",
        bourdet.REF_BOURDET,
    )

    # ---- material balance
    mb = material_balance
    _calc(
        app,
        "material-balance/underground-withdrawal",
        s.UndergroundWithdrawalReq,
        mb.underground_withdrawal,
        lambda b: (
            lambda: mb.underground_withdrawal(
                b.np_stb,
                b.rp_scf_stb,
                b.wp_stb,
                bo_rb_stb=b.bo_rb_stb,
                bg_rb_scf=b.bg_rb_scf,
                rs_scf_stb=b.rs_scf_stb,
                bw_rb_stb=b.bw_rb_stb,
            )
        ),
        "material balance",
        mb.REF_HO,
    )
    _calc(
        app,
        "material-balance/expansion-terms",
        s.ExpansionTermsReq,
        mb.expansion_terms,
        lambda b: (
            lambda: mb.expansion_terms(
                b.p_psia,
                bo_rb_stb=b.bo_rb_stb,
                bg_rb_scf=b.bg_rb_scf,
                rs_scf_stb=b.rs_scf_stb,
                pi_psia=b.pi_psia,
                boi_rb_stb=b.boi_rb_stb,
                bgi_rb_scf=b.bgi_rb_scf,
                rsi_scf_stb=b.rsi_scf_stb,
                cw_per_psi=b.cw_per_psi,
                cf_per_psi=b.cf_per_psi,
                swi=b.swi,
                m=b.m,
            )
        ),
        "material balance",
        mb.REF_HO,
    )
    _calc(
        app,
        "material-balance/fit-no-cap-no-aquifer",
        s.FitNoCapReq,
        mb.fit_no_cap_no_aquifer,
        lambda b: lambda: mb.fit_no_cap_no_aquifer(b.f_rb, b.eo, b.efw, we_rb=b.we_rb),
        "material balance",
        mb.REF_HO,
    )
    _calc(
        app,
        "material-balance/fit-known-m",
        s.FitKnownMReq,
        mb.fit_known_m,
        lambda b: lambda: mb.fit_known_m(b.f_rb, b.eo, b.eg, b.efw, m=b.m, we_rb=b.we_rb),
        "material balance",
        mb.REF_HO,
    )
    _calc(
        app,
        "material-balance/fit-gas-cap-unknown-m",
        s.FitGasCapReq,
        mb.fit_gas_cap_unknown_m,
        lambda b: lambda: mb.fit_gas_cap_unknown_m(b.f_rb, b.eo, b.eg, we_rb=b.we_rb),
        "material balance",
        mb.REF_HO,
    )

    # ---- uncertainty
    def _mc_guard(request_settings: Settings, n: int) -> None:
        if n > request_settings.mc_max_samples:
            raise InputValidationError(
                f"n_samples: received {n}; this server accepts at most "
                f"{request_settings.mc_max_samples}"
            )

    @app.post(
        f"{PREFIX}/calc/uncertainty/mc-archie-sw",
        response_model=s.CalcResponse,
        tags=["uncertainty"],
        responses=ERRORS,
        summary="Monte Carlo distribution of Archie Sw (P90/P50/P10, PRMS convention)",
        description=_doc(uncertainty.mc_archie_sw),
    )
    async def mc_archie(
        request: Request, principal: CalcAuth, body: s.McArchieReq
    ) -> dict[str, Any]:
        _mc_guard(_settings(request), body.n_samples)
        rec = await _run(
            request,
            lambda: uncertainty.mc_archie_sw(
                porosity=_dist(body.porosity),
                rt_ohm_m=_dist(body.rt_ohm_m),
                rw_ohm_m=_dist(body.rw_ohm_m),
                a=_dist(body.a),
                m=_dist(body.m),
                n=_dist(body.n),
                clip=body.clip,
                n_samples=body.n_samples,
                seed=body.seed,
                return_samples=False,
            ),
        )
        return _envelope(principal, rec)

    @app.post(
        f"{PREFIX}/calc/uncertainty/mc-arps-eur",
        response_model=s.CalcResponse,
        tags=["uncertainty"],
        responses=ERRORS,
        summary="Monte Carlo distribution of Arps EUR (P90/P50/P10, PRMS convention)",
        description=_doc(uncertainty.mc_arps_eur),
    )
    async def mc_eur(request: Request, principal: CalcAuth, body: s.McEurReq) -> dict[str, Any]:
        _mc_guard(_settings(request), body.n_samples)
        rec = await _run(
            request,
            lambda: uncertainty.mc_arps_eur(
                qi=_dist(body.qi),
                di=_dist(body.di),
                b=_dist(body.b),
                time_unit=body.time_unit,
                d_terminal=body.d_terminal,
                q_limit=body.q_limit,
                t_horizon=body.t_horizon,
                n_samples=body.n_samples,
                seed=body.seed,
                return_samples=False,
            ),
        )
        return _envelope(principal, rec)

    for fn, path in (
        (uncertainty.mc_archie_sw, "uncertainty/mc-archie-sw"),
        (uncertainty.mc_arps_eur, "uncertainty/mc-arps-eur"),
    ):
        app.state.methods.append(
            s.MethodInfo(
                endpoint=f"POST {PREFIX}/calc/{path}",
                method=f"{fn.__module__}.{fn.__qualname__}",
                maturity=_maturity(fn),
                reference=uncertainty.REF_MC,
            )
        )

    # ---- data uploads
    @app.post(
        f"{PREFIX}/data/las",
        response_model=s.DataResponse,
        tags=["data"],
        responses=ERRORS,
        summary="Read an uploaded LAS 1.2/2.0 file (provenance + validation report)",
    )
    async def upload_las(
        request: Request,
        principal: UploadAuth,
        file: Annotated[UploadFile, File()],
        include_data: Annotated[bool, Form()] = True,
    ) -> dict[str, Any]:
        from georeservoir.io.las import read_las

        await _single_file(request)
        limit = _settings(request).max_upload_bytes

        def work() -> dict[str, Any]:
            with _private_copy(file, limit, ".las") as path:
                log = read_las(path, on_error="report")
            content: dict[str, Any] = {
                "las_version": log.las_version,
                "wrapped": log.wrapped,
                "null_value": log.null_value,
                "index": {
                    "mnemonic": log.index_mnemonic,
                    "unit": log.index_unit,
                    "n": int(log.index.size),
                },
                "canonical_map": dict(log.canonical_map),
                "version_section": [h.to_dict() for h in log.version_section],
                "well_section": [h.to_dict() for h in log.well_section],
                "parameter_section": [h.to_dict() for h in log.parameter_section],
                "other_section": log.other_section,
                "curves": [],
            }
            if include_data:
                content["index"]["values"] = _json_floats(log.index.tolist())
            for name in log.curve_names:
                c = log.curves[name]
                item: dict[str, Any] = {
                    "mnemonic": c.mnemonic,
                    "unit_raw": c.unit_raw,
                    "unit": c.unit,
                    "canonical": c.canonical,
                    "api_code": c.api_code,
                    "description": c.description,
                    "n_null": c.n_null,
                }
                if include_data:
                    item["values"] = _json_floats(c.values.tolist())
                content["curves"].append(item)
            return {
                "api_version": "v1",
                "project_id": principal.project_id,
                "provenance": log.provenance.to_dict(),
                "report": log.report.to_dict(),
                "content": content,
            }

        return await _run(request, work)

    @app.post(
        f"{PREFIX}/data/survey",
        response_model=s.DataResponse,
        tags=["data"],
        responses=ERRORS,
        summary="Read an uploaded directional survey and compute its trajectory",
    )
    async def upload_survey(
        request: Request,
        principal: UploadAuth,
        file: Annotated[UploadFile, File()],
        md_column: Annotated[str, Form(max_length=64)],
        inclination_column: Annotated[str, Form(max_length=64)],
        azimuth_column: Annotated[str, Form(max_length=64)],
        length_unit: Annotated[Literal["m", "ft"], Form()],
        azimuth_reference: Annotated[Literal["true", "magnetic", "grid"], Form()],
        delimiter: Annotated[Literal[",", ";", "tab", "whitespace"], Form()],
        start_east: Annotated[float, Form(allow_inf_nan=False)],
        start_north: Annotated[float, Form(allow_inf_nan=False)],
        start_tvd: Annotated[float, Form(allow_inf_nan=False)],
    ) -> dict[str, Any]:
        from georeservoir.io.survey import read_survey

        await _single_file(request)
        limit = _settings(request).max_upload_bytes

        def work() -> dict[str, Any]:
            with _private_copy(file, limit, ".csv") as path:
                sv = read_survey(
                    path,
                    md_column=md_column,
                    inclination_column=inclination_column,
                    azimuth_column=azimuth_column,
                    length_unit=length_unit,
                    azimuth_reference=azimuth_reference,
                    delimiter="\t" if delimiter == "tab" else delimiter,
                )
            traj = sv.trajectory(
                start_east=start_east, start_north=start_north, start_tvd=start_tvd
            )
            return {
                "api_version": "v1",
                "project_id": principal.project_id,
                "provenance": sv.provenance.to_dict(),
                "report": sv.report.to_dict(),
                "content": {"n_stations": int(sv.md.size), "trajectory": traj.to_dict()},
            }

        return await _run(request, work)


def _bool_array(values: list[bool]) -> Any:
    import numpy as np

    return np.array(values, dtype=bool)


def _json_floats(values: list[float]) -> list[float | None]:
    return [None if v != v else v for v in values]  # NaN → null


async def _single_file(request: Request) -> None:
    form = await request.form()  # already parsed by FastAPI; cached
    if len(form.getlist("file")) != 1:
        raise InputValidationError("file: exactly one file part is required")


class _private_copy:  # noqa: N801 - context manager used like a function
    """Stream the upload (already spooled by the server) into a fresh private temp dir
    under a sanitised base name, enforcing the size limit; removed on exit."""

    def __init__(self, upload: UploadFile, limit: int, default_suffix: str) -> None:
        base = Path((upload.filename or "").replace("\\", "/")).name  # drop directories
        base = _SAFE_NAME.sub("_", base)[:100].lstrip(".") or f"upload{default_suffix}"
        self.upload = upload
        self.limit = limit
        self.base = base
        self.dir: str | None = None

    def __enter__(self) -> Path:
        self.dir = tempfile.mkdtemp(prefix="georeservoir-upload-")
        path = Path(self.dir) / self.base
        size = 0
        src = self.upload.file
        src.seek(0)
        with path.open("xb") as out:  # exclusive create in our own fresh directory
            while chunk := src.read(1024 * 1024):
                size += len(chunk)
                if size > self.limit:
                    raise HTTPException(status_code=413, detail=f"file exceeds {self.limit} bytes")
                out.write(chunk)
        if size == 0:
            raise InputValidationError("file: the uploaded file is empty")
        return path

    def __exit__(self, *exc: object) -> None:
        if self.dir is not None:
            shutil.rmtree(self.dir, ignore_errors=True)
