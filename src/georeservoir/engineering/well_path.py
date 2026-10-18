"""Wellbore trajectory by the Minimum Curvature method.

Conventions
-----------
* Azimuth measured from North, clockwise, in degrees; normalised to [0, 360).
* Axes: East = +X, North = +Y, TVD positive downwards.
* Results are **local wellbore displacements** relative to the given start point,
  never geographic or projected coordinates. Declination / grid-convergence
  corrections are out of scope (A-002).
* Lengths are converted to metres internally and all length outputs are in metres
  (A-001). Use :func:`georeservoir.common.units.length_from_si` to convert back.

Maturity: M2
"""

from __future__ import annotations

from typing import Final, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from georeservoir.common.exceptions import InputValidationError, PhysicalConsistencyError
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.units import FT_TO_M, LengthUnit, length_to_si
from georeservoir.common.validation import (
    as_1d_array,
    check_in_closed_range,
    check_same_length,
    check_strictly_increasing,
    require_finite_scalar,
)

__all__ = [
    "BETA_MAX_RAD",
    "RF_TAYLOR_THRESHOLD_RAD",
    "AzimuthReference",
    "dogleg_angle",
    "minimum_curvature",
    "normalize_azimuth",
    "ratio_factor",
]

AzimuthReference = Literal["true", "magnetic", "grid"]

#: Below this dogleg angle the ratio factor uses its Taylor series (A-003).
RF_TAYLOR_THRESHOLD_RAD: Final[float] = 1e-4
#: Doglegs at or above this angle are rejected: the arc is undefined at β = π (A-004).
BETA_MAX_RAD: Final[float] = np.pi - 1e-6
#: Horizontal displacements below this (m) make the closure azimuth undefined (A-005).
CLOSURE_EPS_M: Final[float] = 1e-12

METHOD_ID: Final[str] = "well_path.minimum_curvature"
METHOD_REF: Final[str] = (
    "Sawaryn, S.J. & Thorogood, J.L. (2005), A Compendium of Directional Calculations "
    "Based on the Minimum Curvature Method, SPE Drilling & Completion 20(1), SPE-84246-PA"
)


def normalize_azimuth(azimuth_deg: ArrayLike) -> NDArray[np.float64]:
    """Map azimuths (degrees) into [0, 360). Returns a new 1-D array.

    Raises
    ------
    InputValidationError
        Non-finite or non-numeric input.

    Maturity: M2
    """
    out = np.mod(as_1d_array("azimuth_deg", azimuth_deg), 360.0)
    out[out >= 360.0] = 0.0  # np.mod(-tiny, 360) can round to 360.0
    return out


def _tangent(inc_rad: NDArray[np.float64], azi_rad: NDArray[np.float64]) -> NDArray[np.float64]:
    """Unit tangent vectors (E, N, TVD), shape (n, 3)."""
    s = np.sin(inc_rad)
    return np.column_stack((s * np.sin(azi_rad), s * np.cos(azi_rad), np.cos(inc_rad)))


def dogleg_angle(
    inc1_rad: ArrayLike,
    azi1_rad: ArrayLike,
    inc2_rad: ArrayLike,
    azi2_rad: ArrayLike,
) -> NDArray[np.float64]:
    """Dogleg angle β (rad) via ``atan2(|t1 × t2|, t1 · t2)``.

    The vector ``atan2`` form is accurate for small β, where the classical
    ``arccos`` formula loses precision.

    Raises
    ------
    InputValidationError
        Non-finite inputs or mismatched lengths.

    Maturity: M2
    """
    i1, a1 = as_1d_array("inc1_rad", inc1_rad), as_1d_array("azi1_rad", azi1_rad)
    i2, a2 = as_1d_array("inc2_rad", inc2_rad), as_1d_array("azi2_rad", azi2_rad)
    check_same_length(inc1_rad=i1, azi1_rad=a1, inc2_rad=i2, azi2_rad=a2)
    t1 = _tangent(i1, a1)
    t2 = _tangent(i2, a2)
    cross = np.linalg.norm(np.cross(t1, t2), axis=1)
    dot = np.einsum("ij,ij->i", t1, t2)
    result: NDArray[np.float64] = np.arctan2(cross, dot)
    return result


def ratio_factor(beta_rad: ArrayLike) -> NDArray[np.float64]:
    """Minimum-curvature ratio factor RF = (2/β)·tan(β/2).

    For β < :data:`RF_TAYLOR_THRESHOLD_RAD` uses ``1 + β²/12 + β⁴/120``
    (truncation error O(β⁶) ≈ 1e-25 at the threshold).

    Raises
    ------
    InputValidationError
        Non-finite β or β outside [0, BETA_MAX_RAD) (RF diverges as β → π, A-004).

    Maturity: M2
    """
    beta = as_1d_array("beta_rad", beta_rad)
    bad = np.flatnonzero((beta < 0.0) | (beta >= BETA_MAX_RAD))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"beta_rad[{i}]: received {beta[i]!r}; expected a value in [0, {BETA_MAX_RAD!r})"
        )
    small = beta < RF_TAYLOR_THRESHOLD_RAD
    rf = np.empty_like(beta)
    b = beta[small]
    rf[small] = 1.0 + b * b / 12.0 + b**4 / 120.0
    bl = beta[~small]
    rf[~small] = 2.0 / bl * np.tan(bl / 2.0)
    return rf


def minimum_curvature(
    md: ArrayLike,
    inclination_deg: ArrayLike,
    azimuth_deg: ArrayLike,
    *,
    length_unit: LengthUnit,
    azimuth_reference: AzimuthReference,
    start_east: float,
    start_north: float,
    start_tvd: float,
) -> CalculationRecord:
    """Compute a wellbore trajectory with the Minimum Curvature method.

    Parameters
    ----------
    md : array_like, shape (n,)
        Measured depth, in ``length_unit``; strictly increasing; n ≥ 2.
    inclination_deg : array_like, shape (n,)
        Inclination in degrees, in [0, 180].
    azimuth_deg : array_like, shape (n,)
        Azimuth in degrees from North, clockwise; any finite value (normalised to [0, 360)).
    length_unit : {"m", "ft"}
        Unit of ``md`` and of the start coordinates.
    azimuth_reference : {"true", "magnetic", "grid"}
        Declared reference of ``azimuth_deg``. Recorded only; no correction applied (A-002).
    start_east, start_north, start_tvd : float
        Coordinates of the first station, in ``length_unit``.

    Returns
    -------
    CalculationRecord
        Station arrays (length n): ``md_m``, ``north_m``, ``east_m``, ``tvd_m``,
        ``horizontal_displacement_m``, ``closure_azimuth_deg``.
        Interval arrays (length n−1, interval i is between stations i and i+1):
        ``delta_north_m``, ``delta_east_m``, ``delta_tvd_m``, ``dogleg_deg``,
        ``dls_deg_per_30m``, ``dls_deg_per_100ft``.

    Raises
    ------
    InputValidationError
        Non-finite values, mismatched lengths, n < 2, MD not strictly increasing,
        inclination outside [0, 180], unsupported unit or reference.
    PhysicalConsistencyError
        A course has a dogleg ≥ π − 1e-6 rad (reversal: the arc is undefined).

    Notes
    -----
    Maturity: M2

    Assumptions: A-001, A-002, A-003, A-004, A-005, A-008.

    The method is exact for circular arcs between stations.

    References
    ----------
    Sawaryn & Thorogood (2005), SPE-84246-PA.
    """
    md_in = as_1d_array("md", md, min_size=2)
    inc = as_1d_array("inclination_deg", inclination_deg, min_size=2)
    azi_raw = as_1d_array("azimuth_deg", azimuth_deg, min_size=2)
    check_same_length(md=md_in, inclination_deg=inc, azimuth_deg=azi_raw)
    check_strictly_increasing("md", md_in)
    check_in_closed_range("inclination_deg", inc, 0.0, 180.0)
    if azimuth_reference not in ("true", "magnetic", "grid"):
        raise InputValidationError(
            f"azimuth_reference: received {azimuth_reference!r}; "
            "expected 'true', 'magnetic' or 'grid'"
        )
    e0 = require_finite_scalar("start_east", start_east)
    n0 = require_finite_scalar("start_north", start_north)
    v0 = require_finite_scalar("start_tvd", start_tvd)

    md_m = length_to_si(md_in, length_unit)
    e0_m, n0_m, v0_m = (float(length_to_si(x, length_unit)) for x in (e0, n0, v0))
    azi = normalize_azimuth(azi_raw)

    inc_r = np.radians(inc)
    azi_r = np.radians(azi)
    i1, i2 = inc_r[:-1], inc_r[1:]
    a1, a2 = azi_r[:-1], azi_r[1:]

    beta = dogleg_angle(i1, a1, i2, a2)
    bad = np.flatnonzero(beta >= BETA_MAX_RAD)
    if bad.size:
        k = int(bad[0])
        raise PhysicalConsistencyError(
            f"dogleg between stations {k} and {k + 1}: received β = {beta[k]!r} rad; "
            f"expected β < {BETA_MAX_RAD!r} rad (a ~180° reversal has no unique arc)"
        )
    rf = ratio_factor(beta)
    dmd = np.diff(md_m)
    half = 0.5 * dmd * rf
    s1, s2 = np.sin(i1), np.sin(i2)
    d_n = half * (s1 * np.cos(a1) + s2 * np.cos(a2))
    d_e = half * (s1 * np.sin(a1) + s2 * np.sin(a2))
    d_v = half * (np.cos(i1) + np.cos(i2))

    north = n0_m + np.concatenate(([0.0], np.cumsum(d_n)))
    east = e0_m + np.concatenate(([0.0], np.cumsum(d_e)))
    tvd = v0_m + np.concatenate(([0.0], np.cumsum(d_v)))

    dn_rel = north - n0_m
    de_rel = east - e0_m
    hd = np.hypot(dn_rel, de_rel)
    closure = normalize_azimuth(np.degrees(np.arctan2(de_rel, dn_rel)))
    # Station 0 is the origin by construction: closure is 0.0 by convention, no warning.
    closure[0] = 0.0
    undefined = np.flatnonzero(hd[1:] < CLOSURE_EPS_M) + 1
    warnings: list[CalcWarning] = []
    if undefined.size:
        closure[undefined] = 0.0
        warnings.append(
            CalcWarning(
                code="CLOSURE_AZIMUTH_UNDEFINED",
                message=(
                    f"horizontal displacement < {CLOSURE_EPS_M} m at {undefined.size} "
                    "station(s); closure azimuth set to 0.0 there (A-005)"
                ),
                indices=tuple(int(i) for i in undefined),
            )
        )

    beta_deg = np.degrees(beta)
    dls_30m = beta_deg / dmd * 30.0
    dls_100ft = beta_deg / (dmd / FT_TO_M) * 100.0

    return make_record(
        method=METHOD_ID,
        method_reference=METHOD_REF,
        maturity="M2",
        values={
            "md_m": md_m,
            "north_m": north,
            "east_m": east,
            "tvd_m": tvd,
            "horizontal_displacement_m": hd,
            "closure_azimuth_deg": closure,
            "delta_north_m": d_n,
            "delta_east_m": d_e,
            "delta_tvd_m": d_v,
            "dogleg_deg": beta_deg,
            "dls_deg_per_30m": dls_30m,
            "dls_deg_per_100ft": dls_100ft,
        },
        units={
            "md_m": "m",
            "north_m": "m",
            "east_m": "m",
            "tvd_m": "m",
            "horizontal_displacement_m": "m",
            "closure_azimuth_deg": "deg",
            "delta_north_m": "m",
            "delta_east_m": "m",
            "delta_tvd_m": "m",
            "dogleg_deg": "deg",
            "dls_deg_per_30m": "deg/30m",
            "dls_deg_per_100ft": "deg/100ft",
        },
        scalar_inputs={
            "length_unit": length_unit,
            "azimuth_reference": azimuth_reference,
            "start_east": e0,
            "start_north": n0,
            "start_tvd": v0,
        },
        array_inputs={"md": md_in, "inclination_deg": inc, "azimuth_deg": azi_raw},
        assumptions=("A-001", "A-002", "A-003", "A-004", "A-005", "A-008"),
        warnings=warnings,
    )
