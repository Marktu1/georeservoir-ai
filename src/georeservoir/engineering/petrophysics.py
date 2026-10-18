"""Deterministic petrophysics: gamma-ray index, shale volume, porosity and Archie.

All outputs are fractions. Results whose *raw* value falls outside [0, 1] are never
clipped silently: a typed warning reports the count and indices, and clipping is
applied only when ``clip=True`` (the raw array is always returned too).

The shale-volume corrections are **empirical correlations**; their applicability
to a given formation must be judged by the petrophysicist. Archie's equation is
valid for clean (clay-free) formations only; shaly-sand models (Simandoux,
Indonesia, Dual-Water) are not implemented in v0.1 (see docs/roadmap.md).

Ratios (porosity, IGR, Sw) are dimensionless, so they are evaluated directly in the
declared input units (A-009).

Maturity: ``archie_water_saturation`` M3; all other functions M2.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import numpy as np
from numpy.typing import ArrayLike, NDArray

from georeservoir.common.exceptions import InputValidationError, PhysicalConsistencyError
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.validation import (
    as_1d_array,
    check_in_closed_range,
    check_positive_scalar,
    require_bool,
    require_finite_scalar,
)

__all__ = [
    "archie_true_resistivity",
    "archie_water_saturation",
    "density_porosity",
    "gamma_ray_index",
    "sonic_porosity_wyllie",
    "vsh_clavier",
    "vsh_larionov_older",
    "vsh_larionov_tertiary",
    "vsh_steiber",
]

REF_IGR: Final[str] = (
    "Linear gamma-ray index; e.g. Asquith, G. & Krygowski, D. (2004), Basic Well Log "
    "Analysis, 2nd ed., AAPG Methods in Exploration 16"
)
REF_LARIONOV: Final[str] = "Larionov, V.V. (1969), Borehole Radiometry, Nedra, Moscow"
REF_STEIBER: Final[str] = (
    "Steiber, R.G. (1970), Pulsed neutron capture log evaluation in the Louisiana Gulf "
    "Coast, SPE-2961-MS"
)
REF_CLAVIER: Final[str] = (
    "Clavier, C., Hoyle, W. & Meunier, D. (1971), Quantitative interpretation of thermal "
    "neutron decay time logs: Part I, Journal of Petroleum Technology 23(6)"
)
REF_DENSITY: Final[str] = (
    "Density-porosity mass balance; e.g. Asquith & Krygowski (2004), Basic Well Log Analysis"
)
REF_WYLLIE: Final[str] = (
    "Wyllie, M.R.J., Gregory, A.R. & Gardner, L.W. (1956), Elastic wave velocities in "
    "heterogeneous and porous media, Geophysics 21(1)"
)
REF_ARCHIE: Final[str] = (
    "Archie, G.E. (1942), The electrical resistivity log as an aid in determining some "
    "reservoir characteristics, Transactions of the AIME 146"
)


def _out_of_unit_range(
    name: str, raw: NDArray[np.float64], clip: bool
) -> tuple[NDArray[np.float64], int, list[CalcWarning]]:
    """Return (output, n_clipped, warnings) for a fraction that should lie in [0, 1]."""
    clip = require_bool("clip", clip)
    bad = np.flatnonzero((raw < 0.0) | (raw > 1.0))
    warnings: list[CalcWarning] = []
    out = raw.copy()
    n_clipped = 0
    if bad.size:
        action = "clipped to [0, 1]" if clip else "returned unclipped (clip=False)"
        warnings.append(
            CalcWarning(
                code="OUT_OF_RANGE_RAW",
                message=f"{bad.size} raw {name} value(s) outside [0, 1]; {action}",
                indices=tuple(int(i) for i in bad),
            )
        )
        if clip:
            out = np.clip(raw, 0.0, 1.0)
            n_clipped = int(bad.size)
    return out, n_clipped, warnings


def gamma_ray_index(
    gr_api: ArrayLike, *, gr_min_api: float, gr_max_api: float, clip: bool
) -> CalculationRecord:
    """Linear gamma-ray index IGR = (GR − GRmin) / (GRmax − GRmin).

    Parameters
    ----------
    gr_api : array_like
        Gamma-ray log, API units.
    gr_min_api, gr_max_api : float
        Clean-sand and shale baselines, API; must satisfy ``gr_max_api > gr_min_api``.
        Always explicit — never estimated implicitly.
    clip : bool
        Clip IGR to [0, 1]. Out-of-range raw values always raise a warning.

    Returns
    -------
    CalculationRecord
        ``igr`` (clipped if requested), ``igr_raw`` and ``n_clipped``.

    Raises
    ------
    InputValidationError
        Non-finite inputs or ``gr_max_api <= gr_min_api``.

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-009.
    """
    gr = as_1d_array("gr_api", gr_api)
    lo = require_finite_scalar("gr_min_api", gr_min_api)
    hi = require_finite_scalar("gr_max_api", gr_max_api)
    if hi <= lo:
        raise InputValidationError(
            f"gr_max_api: received {hi!r} with gr_min_api={lo!r}; expected gr_max_api > gr_min_api"
        )
    raw = (gr - lo) / (hi - lo)
    out, n_clipped, warnings = _out_of_unit_range("IGR", raw, clip)
    return make_record(
        method="petrophysics.gamma_ray_index",
        method_reference=REF_IGR,
        maturity="M2",
        values={"igr": out, "igr_raw": raw, "n_clipped": n_clipped},
        units={"igr": "fraction", "igr_raw": "fraction", "n_clipped": "count"},
        scalar_inputs={"gr_min_api": lo, "gr_max_api": hi, "clip": clip},
        array_inputs={"gr_api": gr},
        assumptions=("A-008", "A-009"),
        warnings=warnings,
    )


def _vsh(
    igr: ArrayLike,
    fn: Callable[[NDArray[np.float64]], NDArray[np.float64]],
    method: str,
    reference: str,
) -> CalculationRecord:
    x = as_1d_array("igr", igr)
    check_in_closed_range("igr", x, 0.0, 1.0)
    vsh = fn(x)
    return make_record(
        method=method,
        method_reference=reference,
        maturity="M2",
        values={"vsh": vsh},
        units={"vsh": "fraction"},
        scalar_inputs={},
        array_inputs={"igr": x},
        assumptions=("A-006", "A-007", "A-008"),
    )


def vsh_larionov_tertiary(igr: ArrayLike) -> CalculationRecord:
    """Larionov (Tertiary / young rocks): Vsh = 0.083·(2^(3.7·IGR) − 1).

    Parameters
    ----------
    igr : array_like
        Gamma-ray index, fraction in [0, 1].

    Returns
    -------
    CalculationRecord
        ``vsh`` (fraction). f(0) = 0; f(1) = 0.083·(2^3.7 − 1) ≈ 0.9957 (empirical, not 1).

    Raises
    ------
    InputValidationError
        IGR non-finite or outside [0, 1].

    Notes
    -----
    Maturity: M2. Empirical correlation. Assumptions: A-006, A-007, A-008.
    """
    return _vsh(
        igr,
        lambda x: 0.083 * (np.exp2(3.7 * x) - 1.0),
        "petrophysics.vsh_larionov_tertiary",
        REF_LARIONOV,
    )


def vsh_larionov_older(igr: ArrayLike) -> CalculationRecord:
    """Larionov (older / consolidated rocks): Vsh = 0.33·(2^(2·IGR) − 1).

    f(0) = 0; f(1) = 0.99 (empirical, not 1). IGR must be in [0, 1].

    Notes
    -----
    Maturity: M2. Empirical correlation. Assumptions: A-006, A-007, A-008.
    """
    return _vsh(
        igr,
        lambda x: 0.33 * (np.exp2(2.0 * x) - 1.0),
        "petrophysics.vsh_larionov_older",
        REF_LARIONOV,
    )


def vsh_steiber(igr: ArrayLike) -> CalculationRecord:
    """Steiber: Vsh = IGR / (3 − 2·IGR).

    f(0) = 0; f(1) = 1 exactly. IGR must be in [0, 1].

    Notes
    -----
    Maturity: M2. Empirical correlation. Assumptions: A-006, A-007, A-008.
    """
    return _vsh(igr, lambda x: x / (3.0 - 2.0 * x), "petrophysics.vsh_steiber", REF_STEIBER)


def vsh_clavier(igr: ArrayLike) -> CalculationRecord:
    """Clavier: Vsh = 1.7 − sqrt(3.38 − (IGR + 0.7)²).

    f(0) = 0 and f(1) = 1 up to floating-point rounding (|error| ≤ ~1e-15, A-007).
    IGR must be in [0, 1].

    Notes
    -----
    Maturity: M2. Empirical correlation. Assumptions: A-006, A-007, A-008.
    """
    return _vsh(
        igr,
        lambda x: 1.7 - np.sqrt(3.38 - (x + 0.7) ** 2),
        "petrophysics.vsh_clavier",
        REF_CLAVIER,
    )


def density_porosity(
    rho_bulk_g_cc: ArrayLike,
    *,
    rho_matrix_g_cc: float,
    rho_fluid_g_cc: float,
    clip: bool,
) -> CalculationRecord:
    """Density porosity φD = (ρma − ρb) / (ρma − ρfl).

    Parameters
    ----------
    rho_bulk_g_cc : array_like
        Bulk density log, g/cm³ (> 0).
    rho_matrix_g_cc, rho_fluid_g_cc : float
        Matrix and fluid densities, g/cm³ (> 0, with ρma > ρfl).
    clip : bool
        Clip φD to [0, 1]; out-of-range raw values always raise a warning.

    Returns
    -------
    CalculationRecord
        ``porosity`` (clipped if requested), ``porosity_raw`` and ``n_clipped``.

    Raises
    ------
    InputValidationError
        Non-finite or non-positive densities.
    PhysicalConsistencyError
        ``rho_matrix_g_cc <= rho_fluid_g_cc``.

    Notes
    -----
    Maturity: M2. No gas, shale or compaction correction (M0, roadmap).
    Assumptions: A-008, A-009.
    """
    rb = as_1d_array("rho_bulk_g_cc", rho_bulk_g_cc)
    _check_positive_array("rho_bulk_g_cc", rb)
    rma = check_positive_scalar("rho_matrix_g_cc", rho_matrix_g_cc)
    rfl = check_positive_scalar("rho_fluid_g_cc", rho_fluid_g_cc)
    if rma <= rfl:
        raise PhysicalConsistencyError(
            f"rho_matrix_g_cc: received {rma!r} with rho_fluid_g_cc={rfl!r}; "
            "expected rho_matrix_g_cc > rho_fluid_g_cc"
        )
    raw = (rma - rb) / (rma - rfl)
    out, n_clipped, warnings = _out_of_unit_range("density porosity", raw, clip)
    return make_record(
        method="petrophysics.density_porosity",
        method_reference=REF_DENSITY,
        maturity="M2",
        values={"porosity": out, "porosity_raw": raw, "n_clipped": n_clipped},
        units={"porosity": "fraction", "porosity_raw": "fraction", "n_clipped": "count"},
        scalar_inputs={"rho_matrix_g_cc": rma, "rho_fluid_g_cc": rfl, "clip": clip},
        array_inputs={"rho_bulk_g_cc": rb},
        assumptions=("A-008", "A-009"),
        warnings=warnings,
    )


def sonic_porosity_wyllie(
    dt_us_per_ft: ArrayLike,
    *,
    dt_matrix_us_per_ft: float,
    dt_fluid_us_per_ft: float,
    clip: bool,
) -> CalculationRecord:
    """Wyllie time-average sonic porosity φS = (Δt − Δtma) / (Δtfl − Δtma).

    Parameters
    ----------
    dt_us_per_ft : array_like
        Compressional slowness log, µs/ft (> 0).
    dt_matrix_us_per_ft, dt_fluid_us_per_ft : float
        Matrix and fluid slowness, µs/ft (> 0, with Δtfl > Δtma).
    clip : bool
        Clip φS to [0, 1]; out-of-range raw values always raise a warning.

    Returns
    -------
    CalculationRecord
        ``porosity`` (clipped if requested), ``porosity_raw`` and ``n_clipped``.

    Raises
    ------
    InputValidationError
        Non-finite or non-positive slowness.
    PhysicalConsistencyError
        ``dt_fluid_us_per_ft <= dt_matrix_us_per_ft``.

    Notes
    -----
    Maturity: M2. No compaction correction; Raymer–Hunt–Gardner is M0 (roadmap).
    Assumptions: A-008, A-009.
    """
    dt = as_1d_array("dt_us_per_ft", dt_us_per_ft)
    _check_positive_array("dt_us_per_ft", dt)
    dma = check_positive_scalar("dt_matrix_us_per_ft", dt_matrix_us_per_ft)
    dfl = check_positive_scalar("dt_fluid_us_per_ft", dt_fluid_us_per_ft)
    if dfl <= dma:
        raise PhysicalConsistencyError(
            f"dt_fluid_us_per_ft: received {dfl!r} with dt_matrix_us_per_ft={dma!r}; "
            "expected dt_fluid_us_per_ft > dt_matrix_us_per_ft"
        )
    raw = (dt - dma) / (dfl - dma)
    out, n_clipped, warnings = _out_of_unit_range("sonic porosity", raw, clip)
    return make_record(
        method="petrophysics.sonic_porosity_wyllie",
        method_reference=REF_WYLLIE,
        maturity="M2",
        values={"porosity": out, "porosity_raw": raw, "n_clipped": n_clipped},
        units={"porosity": "fraction", "porosity_raw": "fraction", "n_clipped": "count"},
        scalar_inputs={
            "dt_matrix_us_per_ft": dma,
            "dt_fluid_us_per_ft": dfl,
            "clip": clip,
        },
        array_inputs={"dt_us_per_ft": dt},
        assumptions=("A-008", "A-009"),
        warnings=warnings,
    )


def _check_positive_array(name: str, arr: NDArray[np.float64]) -> None:
    bad = np.flatnonzero(arr <= 0.0)
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"{name}[{i}]: received {arr[i]!r}; expected a value > 0 "
            f"({bad.size} non-positive element(s))"
        )


def _archie_params(
    a: float, m: float, n: float, rw_ohm_m: float
) -> tuple[float, float, float, float]:
    return (
        check_positive_scalar("a", a),
        check_positive_scalar("m", m),
        check_positive_scalar("n", n),
        check_positive_scalar("rw_ohm_m", rw_ohm_m),
    )


def _check_porosity(porosity: ArrayLike) -> NDArray[np.float64]:
    phi = as_1d_array("porosity", porosity)
    bad = np.flatnonzero((phi <= 0.0) | (phi > 1.0))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"porosity[{i}]: received {phi[i]!r}; expected a fraction in (0, 1]"
        )
    return phi


def _archie_sw(
    phi: NDArray[np.float64] | float,
    rt: NDArray[np.float64] | float,
    rw: NDArray[np.float64] | float,
    a: NDArray[np.float64] | float,
    m: NDArray[np.float64] | float,
    n: NDArray[np.float64] | float,
) -> NDArray[np.float64]:
    """Archie Sw, broadcasting over all arguments (single source of the equation)."""
    out: NDArray[np.float64] = np.power(
        np.multiply(a, rw) / (np.power(phi, m) * rt), np.divide(1.0, n)
    )
    return out


def archie_water_saturation(
    porosity: ArrayLike,
    rt_ohm_m: ArrayLike,
    *,
    rw_ohm_m: float,
    a: float,
    m: float,
    n: float,
    clip: bool,
) -> CalculationRecord:
    """Archie water saturation Sw = (a·Rw / (φ^m · Rt))^(1/n).

    Parameters
    ----------
    porosity : array_like
        Effective porosity, fraction in (0, 1].
    rt_ohm_m : array_like
        True formation resistivity, ohm·m (> 0). Same length as ``porosity``
        (or length 1, broadcast).
    rw_ohm_m : float
        Formation-water resistivity at formation temperature, ohm·m (> 0).
    a, m, n : float
        Tortuosity factor, cementation exponent and saturation exponent (> 0).
        No defaults: the user must choose them for the formation.
    clip : bool
        Clip Sw to [0, 1]; raw Sw > 1 always raises a warning.

    Returns
    -------
    CalculationRecord
        ``sw`` (clipped if requested), ``sw_raw`` and ``n_clipped``.

    Raises
    ------
    InputValidationError
        Non-finite inputs, φ ∉ (0, 1], non-positive Rt, Rw, a, m or n, or
        incompatible lengths.

    Notes
    -----
    Maturity: M3 — reproduces the Kansas Geological Survey PfEFFER 10-zone example
    within its 0.01 rounding (VAL-PP-L01). Valid for clean formations only; clay
    conductivity is ignored and Sw is overestimated in shaly sands. Assumptions: A-008, A-009.
    """
    phi = _check_porosity(porosity)
    rt = as_1d_array("rt_ohm_m", rt_ohm_m)
    _check_positive_array("rt_ohm_m", rt)
    phi, rt = _broadcast_pair("porosity", phi, "rt_ohm_m", rt)
    a_, m_, n_, rw = _archie_params(a, m, n, rw_ohm_m)
    raw = _archie_sw(phi, rt, rw, a_, m_, n_)
    out, n_clipped, warnings = _out_of_unit_range("Sw", raw, clip)
    return make_record(
        method="petrophysics.archie_water_saturation",
        method_reference=REF_ARCHIE,
        maturity="M3",
        values={"sw": out, "sw_raw": raw, "n_clipped": n_clipped},
        units={"sw": "fraction", "sw_raw": "fraction", "n_clipped": "count"},
        scalar_inputs={"rw_ohm_m": rw, "a": a_, "m": m_, "n": n_, "clip": clip},
        array_inputs={"porosity": phi, "rt_ohm_m": rt},
        assumptions=("A-008", "A-009"),
        warnings=warnings,
    )


def archie_true_resistivity(
    porosity: ArrayLike,
    sw: ArrayLike,
    *,
    rw_ohm_m: float,
    a: float,
    m: float,
    n: float,
) -> CalculationRecord:
    """Inverse Archie: Rt = a·Rw / (φ^m · Sw^n), in ohm·m.

    Parameters
    ----------
    porosity : array_like
        Fraction in (0, 1].
    sw : array_like
        Water saturation, fraction in (0, 1].
    rw_ohm_m, a, m, n : float
        As in :func:`archie_water_saturation` (> 0).

    Returns
    -------
    CalculationRecord
        ``rt_ohm_m``.

    Notes
    -----
    Maturity: M2. Clean formations only. Assumptions: A-008, A-009.
    """
    phi = _check_porosity(porosity)
    s = as_1d_array("sw", sw)
    bad = np.flatnonzero((s <= 0.0) | (s > 1.0))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(f"sw[{i}]: received {s[i]!r}; expected a fraction in (0, 1]")
    phi, s = _broadcast_pair("porosity", phi, "sw", s)
    a_, m_, n_, rw = _archie_params(a, m, n, rw_ohm_m)
    rt = a_ * rw / (np.power(phi, m_) * np.power(s, n_))
    return make_record(
        method="petrophysics.archie_true_resistivity",
        method_reference=REF_ARCHIE,
        maturity="M2",
        values={"rt_ohm_m": rt},
        units={"rt_ohm_m": "ohm.m"},
        scalar_inputs={"rw_ohm_m": rw, "a": a_, "m": m_, "n": n_},
        array_inputs={"porosity": phi, "sw": s},
        assumptions=("A-008", "A-009"),
    )


def _broadcast_pair(
    na: str, a: NDArray[np.float64], nb: str, b: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Broadcast two 1-D arrays when one has length 1; otherwise lengths must match."""
    if a.size == b.size:
        return a, b
    if a.size == 1:
        return np.full(b.size, a[0]), b
    if b.size == 1:
        return a, np.full(a.size, b[0])
    raise InputValidationError(
        f"{na} has {a.size} element(s) and {nb} has {b.size}; expected equal lengths "
        "or one of length 1"
    )
