"""Request/response models. Requests forbid unknown fields and non-finite numbers."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, Strict, StrictBool, StrictInt

#: Hard schema cap on array length; a stricter runtime limit comes from Settings.
SCHEMA_MAX_ARRAY: Final[int] = 1_000_000

#: JSON numbers only: ints accepted, booleans and numeric strings refused (A-027)
Finite = Annotated[float, Strict(), Field(allow_inf_nan=False)]
Arr = Annotated[list[Finite], Field(min_length=1, max_length=SCHEMA_MAX_ARRAY)]
LengthUnit = Literal["m", "ft"]
PressureUnit = Literal["Pa", "kPa", "MPa", "psi", "bar"]
TimeUnit = Literal["day", "month", "year"]


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


# ------------------------------------------------------------------ well path
class MinimumCurvatureReq(Req):
    md: Arr
    inclination_deg: Arr
    azimuth_deg: Arr
    length_unit: LengthUnit
    azimuth_reference: Literal["true", "magnetic", "grid"]
    start_east: Finite
    start_north: Finite
    start_tvd: Finite


# ------------------------------------------------------------------ petrophysics
class GammaRayIndexReq(Req):
    gr_api: Arr
    gr_min_api: Finite
    gr_max_api: Finite
    clip: StrictBool


class VshReq(Req):
    igr: Arr
    method: Literal["larionov_tertiary", "larionov_older", "steiber", "clavier"]


class DensityPorosityReq(Req):
    rho_bulk_g_cc: Arr
    rho_matrix_g_cc: Finite
    rho_fluid_g_cc: Finite
    clip: StrictBool


class SonicPorosityReq(Req):
    dt_us_per_ft: Arr
    dt_matrix_us_per_ft: Finite
    dt_fluid_us_per_ft: Finite
    clip: StrictBool


class ArchieParams(Req):
    rw_ohm_m: Finite
    a: Finite
    m: Finite
    n: Finite


class ArchieSwReq(ArchieParams):
    porosity: Arr
    rt_ohm_m: Arr
    clip: StrictBool


class ArchieRtReq(ArchieParams):
    porosity: Arr
    sw: Arr


# ------------------------------------------------------------------ DCA
class ArpsReq(Req):
    t: Arr
    qi: Finite
    di: Finite
    b: Finite
    time_unit: TimeUnit
    d_terminal: Finite | None


class ArpsEurReq(Req):
    qi: Finite
    di: Finite
    b: Finite
    time_unit: TimeUnit
    d_terminal: Finite | None
    q_limit: Finite | None
    t_horizon: Finite | None


class ArpsFitReq(Req):
    t: Arr
    q: Arr
    include: Annotated[list[StrictBool], Field(min_length=1, max_length=SCHEMA_MAX_ARRAY)]
    time_unit: TimeUnit


class DeclineConversionReq(Req):
    values: Arr
    b: Finite


# ------------------------------------------------------------------ nodal
class IprReq(Req):
    model: Literal["linear", "vogel", "composite"]
    pwf: Arr
    p_res: Finite
    pressure_unit: PressureUnit
    j: Finite | None = None
    q_max: Finite | None = None
    p_bubble: Finite | None = None


class VogelQmaxReq(Req):
    p_res: Finite
    q_test: Finite
    pwf_test: Finite
    pressure_unit: PressureUnit


class CompositeJReq(VogelQmaxReq):
    p_bubble: Finite


class NodalSolveReq(Req):
    ipr: IprReq
    tpr_q: Arr
    tpr_pwf: Arr
    n_grid: Annotated[StrictInt, Field(ge=10, le=100_000)]
    xtol: Finite
    maxiter: Annotated[StrictInt, Field(ge=1, le=10_000)]


# ------------------------------------------------------------------ Bourdet
class BourdetReq(Req):
    dt: Arr
    dp: Arr
    window_ln: Finite
    sigma_p: Finite
    pressure_unit: PressureUnit


# ------------------------------------------------------------------ material balance
class UndergroundWithdrawalReq(Req):
    np_stb: Arr
    rp_scf_stb: Arr
    wp_stb: Arr
    bo_rb_stb: Arr
    bg_rb_scf: Arr
    rs_scf_stb: Arr
    bw_rb_stb: Arr


class ExpansionTermsReq(Req):
    p_psia: Arr
    bo_rb_stb: Arr
    bg_rb_scf: Arr
    rs_scf_stb: Arr
    pi_psia: Finite
    boi_rb_stb: Finite
    bgi_rb_scf: Finite
    rsi_scf_stb: Finite
    cw_per_psi: Finite
    cf_per_psi: Finite
    swi: Finite
    m: Finite


class FitNoCapReq(Req):
    f_rb: Arr
    eo: Arr
    efw: Arr
    we_rb: Arr | None


class FitKnownMReq(Req):
    f_rb: Arr
    eo: Arr
    eg: Arr
    efw: Arr
    m: Finite
    we_rb: Arr | None


class FitGasCapReq(Req):
    f_rb: Arr
    eo: Arr
    eg: Arr
    we_rb: Arr | None


# ------------------------------------------------------------------ uncertainty
class DFixed(Req):
    kind: Literal["fixed"]
    value: Finite


class DUniform(Req):
    kind: Literal["uniform"]
    low: Finite
    high: Finite


class DTriangular(Req):
    kind: Literal["triangular"]
    low: Finite
    mode: Finite
    high: Finite


class DNormal(Req):
    kind: Literal["normal"]
    mean: Finite
    sd: Finite
    low: Finite | None
    high: Finite | None


class DLogNormal(Req):
    kind: Literal["lognormal"]
    median: Finite
    sigma_ln: Finite


Dist = Annotated[
    DFixed | DUniform | DTriangular | DNormal | DLogNormal, Field(discriminator="kind")
]


class McArchieReq(Req):
    porosity: Dist
    rt_ohm_m: Dist
    rw_ohm_m: Dist
    a: Dist
    m: Dist
    n: Dist
    clip: StrictBool
    n_samples: StrictInt
    seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]


class McEurReq(Req):
    qi: Dist
    di: Dist
    b: Dist
    time_unit: TimeUnit
    d_terminal: Finite | None
    q_limit: Finite | None
    t_horizon: Finite | None
    n_samples: StrictInt
    seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]


# ------------------------------------------------------------------ responses
class WarningModel(BaseModel):
    code: str
    message: str
    indices: list[int]


class CalculationRecordModel(BaseModel):
    """Serialised ``georeservoir.common.record.CalculationRecord`` (contract v1)."""

    values: dict[str, Any]
    units: dict[str, str]
    method: str
    method_reference: str
    inputs: dict[str, Any]
    inputs_hash: str
    library_version: str
    maturity: Literal["M0", "M1", "M2", "M3"]
    assumptions: list[str]
    warnings: list[WarningModel]


class CalcResponse(BaseModel):
    api_version: Literal["v1"]
    project_id: str
    record: CalculationRecordModel


class ErrorBody(BaseModel):
    type: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class MethodInfo(BaseModel):
    endpoint: str
    method: str
    maturity: str
    reference: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    api_version: Literal["v1"]
    library_version: str


class DataResponse(BaseModel):
    """LAS or survey file read result (provenance + validation report + data)."""

    api_version: Literal["v1"]
    project_id: str
    provenance: dict[str, Any]
    report: dict[str, Any]
    content: dict[str, Any]
