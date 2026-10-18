"""Oil material balance in the Havlena–Odeh straight-line form (field units).

    F = N·(Eo + m·Eg + Efw) + We

    F   = Np·[Bo + (Rp − Rs)·Bg] + Wp·Bw
    Eo  = (Bo − Boi) + (Rsi − Rs)·Bg
    Eg  = Boi·(Bg/Bgi − 1)
    Efw = (1 + m)·Boi·(cw·Swi + cf)/(1 − Swi)·Δp,   Δp = pi − p

Units (A-017): Bo, Bw in rb/STB; Bg in rb/scf; Rs, Rp in scf/STB; Np, Wp in STB;
pressures in psia; cw, cf in 1/psi; F, Eo·N in rb; N in STB. ``We`` (rb) is only a
user-supplied series — Fetkovich and Carter–Tracy aquifers are separate models (M0).

Supported fits, each its own function:
  (a) no gas cap, no aquifer: F vs (Eo + Efw) through the origin → N
  (b) known gas-cap ratio m:  F vs (Eo + m·Eg + Efw) through the origin → N
  (c) unknown m: F/Eo vs Eg/Eo (straight line, Efw neglected) → N (intercept), m

Maturity: M2
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import ArrayLike, NDArray

from georeservoir.common.exceptions import (
    IdentifiabilityError,
    InputValidationError,
    PhysicalConsistencyError,
)
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.validation import (
    as_1d_array,
    check_positive_scalar,
    check_same_length,
    require_finite_scalar,
)

__all__ = [
    "expansion_terms",
    "fit_gas_cap_unknown_m",
    "fit_known_m",
    "fit_no_cap_no_aquifer",
    "underground_withdrawal",
]

REF_HO: Final[str] = (
    "Havlena, D. & Odeh, A.S. (1963), The Material Balance as an Equation of a Straight "
    "Line, Journal of Petroleum Technology 15(8), SPE-559-PA"
)
#: Maximum condition number of the (scaled) design matrix in fit (c).
MAX_CONDITION: Final[float] = 1e8


def _nonneg(name: str, a: NDArray[np.float64]) -> None:
    bad = np.flatnonzero(a < 0.0)
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(f"{name}[{i}]: received {a[i]!r}; expected a value >= 0")


def _pos(name: str, a: NDArray[np.float64]) -> None:
    bad = np.flatnonzero(a <= 0.0)
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(f"{name}[{i}]: received {a[i]!r}; expected a value > 0")


def underground_withdrawal(
    np_stb: ArrayLike,
    rp_scf_stb: ArrayLike,
    wp_stb: ArrayLike,
    *,
    bo_rb_stb: ArrayLike,
    bg_rb_scf: ArrayLike,
    rs_scf_stb: ArrayLike,
    bw_rb_stb: ArrayLike,
) -> CalculationRecord:
    """Underground withdrawal F = Np·[Bo + (Rp − Rs)·Bg] + Wp·Bw, in rb.

    All arguments are 1-D arrays of the same length (one value per pressure step).
    Np, Wp >= 0; Rp >= 0; Bo, Bg, Bw > 0; Rs >= 0.

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-017.
    """
    n_ = as_1d_array("np_stb", np_stb)
    rp = as_1d_array("rp_scf_stb", rp_scf_stb)
    wp = as_1d_array("wp_stb", wp_stb)
    bo = as_1d_array("bo_rb_stb", bo_rb_stb)
    bg = as_1d_array("bg_rb_scf", bg_rb_scf)
    rs = as_1d_array("rs_scf_stb", rs_scf_stb)
    bw = as_1d_array("bw_rb_stb", bw_rb_stb)
    check_same_length(
        np_stb=n_,
        rp_scf_stb=rp,
        wp_stb=wp,
        bo_rb_stb=bo,
        bg_rb_scf=bg,
        rs_scf_stb=rs,
        bw_rb_stb=bw,
    )
    for name, a in (("np_stb", n_), ("rp_scf_stb", rp), ("wp_stb", wp), ("rs_scf_stb", rs)):
        _nonneg(name, a)
    for name, a in (("bo_rb_stb", bo), ("bg_rb_scf", bg), ("bw_rb_stb", bw)):
        _pos(name, a)
    f = n_ * (bo + (rp - rs) * bg) + wp * bw
    return make_record(
        method="material_balance.underground_withdrawal",
        method_reference=REF_HO,
        maturity="M2",
        values={"f_rb": f},
        units={"f_rb": "rb"},
        scalar_inputs={},
        array_inputs={
            "np_stb": n_,
            "rp_scf_stb": rp,
            "wp_stb": wp,
            "bo_rb_stb": bo,
            "bg_rb_scf": bg,
            "rs_scf_stb": rs,
            "bw_rb_stb": bw,
        },
        assumptions=("A-008", "A-017"),
    )


def expansion_terms(
    p_psia: ArrayLike,
    *,
    bo_rb_stb: ArrayLike,
    bg_rb_scf: ArrayLike,
    rs_scf_stb: ArrayLike,
    pi_psia: float,
    boi_rb_stb: float,
    bgi_rb_scf: float,
    rsi_scf_stb: float,
    cw_per_psi: float,
    cf_per_psi: float,
    swi: float,
    m: float,
) -> CalculationRecord:
    """Expansion terms Eo, Eg (rb/STB) and Efw (rb/STB) of the Havlena–Odeh equation.

    Parameters
    ----------
    p_psia : array_like
        Average reservoir pressure at each step (> 0, <= pi).
    bo_rb_stb, bg_rb_scf, rs_scf_stb : array_like
        PVT at each step (Bo, Bg > 0; Rs >= 0).
    pi_psia, boi_rb_stb, bgi_rb_scf, rsi_scf_stb : float
        Initial pressure and PVT (> 0; Rsi >= 0).
    cw_per_psi, cf_per_psi : float
        Water and pore compressibilities (>= 0).
    swi : float
        Initial water saturation, fraction in [0, 1).
    m : float
        Gas-cap to oil-zone initial volume ratio (>= 0; 0 = no gas cap). Enters Efw.

    Returns
    -------
    CalculationRecord
        ``eo``, ``eg`` and ``efw`` (rb/STB) and ``dp_psi``.

    Raises
    ------
    InputValidationError
        Invalid values or shapes.
    PhysicalConsistencyError
        A pressure above the initial pressure.

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-017.
    """
    p = as_1d_array("p_psia", p_psia)
    bo = as_1d_array("bo_rb_stb", bo_rb_stb)
    bg = as_1d_array("bg_rb_scf", bg_rb_scf)
    rs = as_1d_array("rs_scf_stb", rs_scf_stb)
    check_same_length(p_psia=p, bo_rb_stb=bo, bg_rb_scf=bg, rs_scf_stb=rs)
    _pos("p_psia", p)
    _pos("bo_rb_stb", bo)
    _pos("bg_rb_scf", bg)
    _nonneg("rs_scf_stb", rs)
    pi = check_positive_scalar("pi_psia", pi_psia)
    boi = check_positive_scalar("boi_rb_stb", boi_rb_stb)
    bgi = check_positive_scalar("bgi_rb_scf", bgi_rb_scf)
    rsi = require_finite_scalar("rsi_scf_stb", rsi_scf_stb)
    cw = require_finite_scalar("cw_per_psi", cw_per_psi)
    cf = require_finite_scalar("cf_per_psi", cf_per_psi)
    sw = require_finite_scalar("swi", swi)
    m_ = require_finite_scalar("m", m)
    for name, v in (("rsi_scf_stb", rsi), ("cw_per_psi", cw), ("cf_per_psi", cf), ("m", m_)):
        if v < 0.0:
            raise InputValidationError(f"{name}: received {v!r}; expected a value >= 0")
    if not 0.0 <= sw < 1.0:
        raise InputValidationError(f"swi: received {sw!r}; expected a fraction in [0, 1)")
    above = np.flatnonzero(p > pi)
    if above.size:
        i = int(above[0])
        raise PhysicalConsistencyError(
            f"p_psia[{i}]: received {p[i]!r} above pi_psia = {pi!r}; depletion data must "
            "satisfy p <= pi"
        )
    dp = pi - p
    eo = (bo - boi) + (rsi - rs) * bg
    eg = boi * (bg / bgi - 1.0)
    efw = (1.0 + m_) * boi * (cw * sw + cf) / (1.0 - sw) * dp
    return make_record(
        method="material_balance.expansion_terms",
        method_reference=REF_HO,
        maturity="M2",
        values={"eo": eo, "eg": eg, "efw": efw, "dp_psi": dp},
        units={"eo": "rb/STB", "eg": "rb/STB", "efw": "rb/STB", "dp_psi": "psi"},
        scalar_inputs={
            "pi_psia": pi,
            "boi_rb_stb": boi,
            "bgi_rb_scf": bgi,
            "rsi_scf_stb": rsi,
            "cw_per_psi": cw,
            "cf_per_psi": cf,
            "swi": sw,
            "m": m_,
        },
        array_inputs={"p_psia": p, "bo_rb_stb": bo, "bg_rb_scf": bg, "rs_scf_stb": rs},
        assumptions=("A-008", "A-017"),
    )


def _we(we_rb: ArrayLike | None, n: int) -> NDArray[np.float64]:
    if we_rb is None:
        return np.zeros(n)
    w = as_1d_array("we_rb", we_rb)
    if w.size != n:
        raise InputValidationError(f"we_rb: received {w.size} element(s); expected {n}")
    _nonneg("we_rb", w)
    return w


def _through_origin(
    method: str,
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    arrays: dict[str, NDArray[np.float64]],
    scalars: dict[str, float | str],
    warnings: list[CalcWarning],
) -> CalculationRecord:
    n = x.size
    if n < 2:
        raise IdentifiabilityError(
            f"{n} point(s) given; at least 2 are needed to estimate N with a residual"
        )
    sxx = float(x @ x)
    if sxx <= 0.0 or float(np.max(np.abs(x))) <= 1e-12 * max(1.0, float(np.max(np.abs(y)))):
        raise IdentifiabilityError(
            "expansion terms are all ~0: N is not identifiable (no depletion yet?)"
        )
    nn = float(x @ y) / sxx
    if nn <= 0.0:
        raise PhysicalConsistencyError(
            f"fitted N = {nn!r} STB is not positive: data inconsistent with the model "
            "(check signs of F − We and the expansion terms)"
        )
    neg = np.flatnonzero(x < 0.0)
    if neg.size:
        warnings = [
            *warnings,
            CalcWarning(
                "NEGATIVE_EXPANSION",
                f"{neg.size} expansion value(s) < 0: physically unexpected for depletion",
                tuple(int(i) for i in neg),
            ),
        ]
    res = y - nn * x
    s2 = float(res @ res) / (n - 1)
    se = float(np.sqrt(s2 / sxx))
    ss_tot = float(y @ y)  # uncentred R² for a regression through the origin
    r2 = 1.0 - float(res @ res) / ss_tot if ss_tot > 0 else 1.0
    return make_record(
        method=method,
        method_reference=REF_HO,
        maturity="M2",
        values={
            "n_stb": nn,
            "n_se_stb": se,
            "r2_uncentred": r2,
            "residual_rb": res,
            "n_points": n,
        },
        units={
            "n_stb": "STB",
            "n_se_stb": "STB",
            "r2_uncentred": "dimensionless",
            "residual_rb": "rb",
            "n_points": "count",
        },
        scalar_inputs=scalars,
        array_inputs=arrays,
        assumptions=("A-008", "A-017", "A-018"),
        warnings=warnings,
    )


def fit_no_cap_no_aquifer(
    f_rb: ArrayLike, eo: ArrayLike, efw: ArrayLike, *, we_rb: ArrayLike | None
) -> CalculationRecord:
    """Case (a): N from (F − We) = N·(Eo + Efw), least squares through the origin.

    Parameters
    ----------
    f_rb : array_like
        Underground withdrawal F (rb), one value per pressure step.
    eo, efw : array_like
        Expansion terms (rb/STB) from :func:`expansion_terms` with m = 0.
    we_rb : array_like or None
        User-supplied cumulative water influx (rb) or ``None`` (no aquifer).

    Returns
    -------
    CalculationRecord
        ``n_stb``, ``n_se_stb``, ``r2_uncentred``, ``residual_rb``, ``n_points``.

    Raises
    ------
    IdentifiabilityError
        Fewer than 2 points or all expansion terms ~0.

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-017, A-018.
    """
    f = as_1d_array("f_rb", f_rb)
    e1 = as_1d_array("eo", eo)
    e2 = as_1d_array("efw", efw)
    check_same_length(f_rb=f, eo=e1, efw=e2)
    w = _we(we_rb, f.size)
    return _through_origin(
        "material_balance.fit_no_cap_no_aquifer",
        e1 + e2,
        f - w,
        {"f_rb": f, "eo": e1, "efw": e2, "we_rb": w},
        {"aquifer": "none" if we_rb is None else "user series"},
        [],
    )


def fit_known_m(
    f_rb: ArrayLike,
    eo: ArrayLike,
    eg: ArrayLike,
    efw: ArrayLike,
    *,
    m: float,
    we_rb: ArrayLike | None,
) -> CalculationRecord:
    """Case (b): N from (F − We) = N·(Eo + m·Eg + Efw) with known gas-cap ratio m.

    ``efw`` must have been computed with the same ``m`` (it carries the (1 + m) factor).

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-017, A-018.
    """
    f = as_1d_array("f_rb", f_rb)
    e1 = as_1d_array("eo", eo)
    e2 = as_1d_array("eg", eg)
    e3 = as_1d_array("efw", efw)
    check_same_length(f_rb=f, eo=e1, eg=e2, efw=e3)
    m_ = require_finite_scalar("m", m)
    if m_ < 0.0:
        raise InputValidationError(f"m: received {m_!r}; expected m >= 0")
    w = _we(we_rb, f.size)
    return _through_origin(
        "material_balance.fit_known_m",
        e1 + m_ * e2 + e3,
        f - w,
        {"f_rb": f, "eo": e1, "eg": e2, "efw": e3, "we_rb": w},
        {"m": m_, "aquifer": "none" if we_rb is None else "user series"},
        [],
    )


def fit_gas_cap_unknown_m(
    f_rb: ArrayLike, eo: ArrayLike, eg: ArrayLike, *, we_rb: ArrayLike | None
) -> CalculationRecord:
    """Case (c): (F − We)/Eo = N + N·m·(Eg/Eo); intercept → N, slope/intercept → m.

    Efw is neglected (A-018), as in the classic Havlena–Odeh gas-cap plot.

    Returns
    -------
    CalculationRecord
        ``n_stb``, ``m``, ``n_se_stb``, ``nm_se_stb`` (s.e. of slope N·m), ``r2``,
        ``residual`` (in F/Eo units, STB) and ``n_points``.

    Raises
    ------
    InputValidationError
        Any Eo <= 0 (F/Eo undefined).
    IdentifiabilityError
        Fewer than 3 points or ill-conditioned design (Eg/Eo nearly constant).

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-017, A-018.
    """
    f = as_1d_array("f_rb", f_rb)
    e1 = as_1d_array("eo", eo)
    e2 = as_1d_array("eg", eg)
    check_same_length(f_rb=f, eo=e1, eg=e2)
    _pos("eo", e1)
    w = _we(we_rb, f.size)
    n = f.size
    if n < 3:
        raise IdentifiabilityError(
            f"{n} point(s) given; at least 3 are needed to fit intercept and slope"
        )
    y = (f - w) / e1
    x = e2 / e1
    # column-normalised (not centred) design: collinearity of [1, Eg/Eo] shows up here
    design = np.column_stack((np.ones(n), x))
    norms = np.linalg.norm(design, axis=0)
    cond = float(np.linalg.cond(design / np.where(norms > 0, norms, 1.0)))
    if not np.isfinite(cond) or cond > MAX_CONDITION:
        raise IdentifiabilityError(
            f"Eg/Eo is (nearly) constant across the data (condition number {cond:.3e} > "
            f"{MAX_CONDITION:.0e}): N and m cannot be separated"
        )
    a = np.column_stack((np.ones(n), x))
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    intercept, slope = float(coef[0]), float(coef[1])
    res = y - a @ coef
    s2 = float(res @ res) / (n - 2)
    cov = s2 * np.linalg.inv(a.T @ a)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(res @ res) / ss_tot if ss_tot > 0 else 1.0
    warnings: list[CalcWarning] = []
    if intercept <= 0.0:
        raise PhysicalConsistencyError(
            f"fitted N = {intercept!r} STB is not positive: data inconsistent with the model"
        )
    m_fit = slope / intercept
    if m_fit < 0.0:
        warnings.append(
            CalcWarning(
                "NEGATIVE_M",
                f"fitted m = {m_fit:.4g} < 0: inconsistent with a gas "
                "cap (check PVT, We or data quality)",
            )
        )
    return make_record(
        method="material_balance.fit_gas_cap_unknown_m",
        method_reference=REF_HO,
        maturity="M2",
        values={
            "n_stb": intercept,
            "m": m_fit,
            "n_se_stb": float(np.sqrt(cov[0, 0])),
            "nm_se_stb": float(np.sqrt(cov[1, 1])),
            "r2": r2,
            "residual": res,
            "n_points": n,
        },
        units={
            "n_stb": "STB",
            "m": "dimensionless",
            "n_se_stb": "STB",
            "nm_se_stb": "STB",
            "r2": "dimensionless",
            "residual": "STB",
            "n_points": "count",
        },
        scalar_inputs={"aquifer": "none" if we_rb is None else "user series"},
        array_inputs={"f_rb": f, "eo": e1, "eg": e2, "we_rb": w},
        assumptions=("A-008", "A-017", "A-018"),
        warnings=warnings,
    )
