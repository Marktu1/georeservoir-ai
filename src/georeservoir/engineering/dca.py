"""Decline Curve Analysis — Arps (exponential, hyperbolic, harmonic, modified hyperbolic).

Conventions
-----------
* ``di`` / ``d_terminal`` are **nominal instantaneous** decline rates, per ``time_unit``.
* ``time_unit`` is mandatory: ``"day"``, ``"month"`` or ``"year"``. A year is 365.25 days
  and a month is 1/12 year (A-010).
* Rates are in any volumetric rate unit (e.g. STB/d); cumulatives are rate unit × time
  unit, so the caller must keep them consistent (e.g. STB/month with ``time_unit="month"``).
* Rate uses ``q = qi·exp(−log1p(b·Di·t)/b)``; for b < :data:`B_EXP_THRESHOLD` the
  exponential limit is used (A-011). Cumulatives use closed forms with ``expm1``/``log1p``.

Maturity: ``nominal_to_effective_decline`` M3 (reproduces the published SPEE REP #6
table); all other functions M2.
"""

from __future__ import annotations

from typing import Final, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import least_squares

from georeservoir.common.exceptions import (
    IdentifiabilityError,
    InputValidationError,
    NumericalError,
)
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.validation import (
    as_1d_array,
    check_positive_scalar,
    check_same_length,
    require_finite_scalar,
)

__all__ = [
    "B_EXP_THRESHOLD",
    "TimeUnit",
    "arps_cumulative",
    "arps_eur",
    "arps_fit",
    "arps_rate",
    "convert_nominal_decline",
    "effective_to_nominal_decline",
    "nominal_to_effective_decline",
]

TimeUnit = Literal["day", "month", "year"]

#: Below this b, the exponential limit (b = 0) is used (A-011).
B_EXP_THRESHOLD: Final[float] = 1e-10
B_MAX: Final[float] = 2.0
DAYS_PER: Final[dict[str, float]] = {"day": 1.0, "month": 365.25 / 12.0, "year": 365.25}

REF_ARPS: Final[str] = (
    "Arps, J.J. (1945), Analysis of Decline Curves, Transactions of the AIME 160, SPE-945228-G"
)
REF_SPEE: Final[str] = (
    "SPEE Recommended Evaluation Practice #6, Definition of Decline Curve Parameters "
    "(Society of Petroleum Evaluation Engineers, 2002)"
)


# --------------------------------------------------------------------------- helpers
def _time_unit(time_unit: str) -> str:
    if not isinstance(time_unit, str) or time_unit not in DAYS_PER:
        raise InputValidationError(
            f"time_unit: received {time_unit!r}; expected 'day', 'month' or 'year'"
        )
    return time_unit


def _b(b: float) -> float:
    v = require_finite_scalar("b", b)
    if not 0.0 <= v <= B_MAX:
        raise InputValidationError(f"b: received {v!r}; expected a value in [0, {B_MAX}]")
    return v


def _b_warnings(b: float) -> list[CalcWarning]:
    if b > 1.0:
        return [
            CalcWarning(
                "B_GREATER_THAN_ONE",
                f"b = {b} > 1: typical of transient flow in low-permeability reservoirs, "
                "not of boundary-dominated flow; long extrapolations overestimate reserves",
            )
        ]
    return []


def _terminal_warnings(di: float, dt: float | None) -> list[CalcWarning]:
    if dt is not None and dt >= di:
        return [
            CalcWarning(
                "TERMINAL_DECLINE_EXCEEDS_INITIAL",
                f"d_terminal = {dt} >= di = {di}: the curve is exponential at d_terminal "
                "from t = 0 (di is not used)",
            )
        ]
    return []


def _check_times(t: NDArray[np.float64]) -> None:
    bad = np.flatnonzero(t < 0.0)
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(f"t[{i}]: received {t[i]!r}; expected t >= 0")


def _rate(t: NDArray[np.float64], qi: float, di: float, b: float) -> NDArray[np.float64]:
    if b < B_EXP_THRESHOLD:
        out: NDArray[np.float64] = qi * np.exp(-di * t)
        return out
    out = qi * np.exp(-np.log1p(b * di * t) / b)
    return out


def _cum(t: NDArray[np.float64], qi: float, di: float, b: float) -> NDArray[np.float64]:
    if b < B_EXP_THRESHOLD:
        out: NDArray[np.float64] = qi / di * -np.expm1(-di * t)
        return out
    if b == 1.0:
        out = qi / di * np.log1p(di * t)
        return out
    x = (b - 1.0) / b * np.log1p(b * di * t)
    out = qi / ((1.0 - b) * di) * -np.expm1(x)
    return out


def _switch_time(di: float, b: float, d_terminal: float) -> float:
    """Time at which the hyperbolic decline D(t) = Di/(1 + b·Di·t) falls to d_terminal."""
    if b < B_EXP_THRESHOLD or d_terminal >= di:
        return 0.0
    return (di / d_terminal - 1.0) / (b * di)


def _modified(
    t: NDArray[np.float64], qi: float, di: float, b: float, d_terminal: float | None
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """(rate, cumulative) for Arps, with optional switch to exponential at d_terminal."""
    if d_terminal is None:
        return _rate(t, qi, di, b), _cum(t, qi, di, b)
    if b < B_EXP_THRESHOLD or d_terminal >= di:
        # already at or below terminal decline: pure exponential at max(di, d_terminal)
        d = max(di, d_terminal)
        return _rate(t, qi, d, 0.0), _cum(t, qi, d, 0.0)
    ts = _switch_time(di, b, d_terminal)
    qs = float(_rate(np.array([ts]), qi, di, b)[0])
    ns = float(_cum(np.array([ts]), qi, di, b)[0])
    before = t <= ts
    dt_after = np.maximum(t - ts, 0.0)  # np.where evaluates both branches
    q = np.where(before, _rate(t, qi, di, b), qs * np.exp(-d_terminal * dt_after))
    np_ = np.where(
        before, _cum(t, qi, di, b), ns + qs / d_terminal * -np.expm1(-d_terminal * dt_after)
    )
    return q, np_


def _terminal(d_terminal: float | None, di: float) -> float | None:
    if d_terminal is None:
        return None
    return check_positive_scalar("d_terminal", d_terminal)


# --------------------------------------------------------------------------- public API
def arps_rate(
    t: ArrayLike,
    *,
    qi: float,
    di: float,
    b: float,
    time_unit: TimeUnit,
    d_terminal: float | None,
) -> CalculationRecord:
    """Arps production rate q(t), optionally modified hyperbolic.

    Parameters
    ----------
    t : array_like
        Time since start of decline, in ``time_unit`` (>= 0).
    qi : float
        Initial rate (> 0), any rate unit; ``q`` is returned in the same unit.
    di : float
        Initial nominal decline per ``time_unit`` (> 0).
    b : float
        Hyperbolic exponent in [0, 2]; 0 = exponential, 1 = harmonic.
    time_unit : {"day", "month", "year"}
        Unit of ``t``, ``di`` and ``d_terminal``.
    d_terminal : float or None
        Terminal nominal decline per ``time_unit`` (> 0). When given, the decline switches
        to exponential once D(t) = d_terminal (modified hyperbolic). ``None`` = pure Arps.

    Returns
    -------
    CalculationRecord
        ``q`` (rate unit of ``qi``) and ``switch_time`` (``time_unit``; 0 if no switch).

    Raises
    ------
    InputValidationError
        Non-finite inputs, t < 0, non-positive qi/di/d_terminal, b outside [0, 2],
        unknown ``time_unit``.

    Notes
    -----
    Maturity: M2 — verified against quadrature (cumulative) and continuity properties;
    also consistent with SPEE REP #6 Table 1 at t = 1 year (VAL-DCA-002x), which is the
    same evidence as the conversion function and is not counted twice.
    Assumptions: A-008, A-010, A-011.
    """
    tt = as_1d_array("t", t)
    _check_times(tt)
    qi_ = check_positive_scalar("qi", qi)
    di_ = check_positive_scalar("di", di)
    b_ = _b(b)
    tu = _time_unit(time_unit)
    dt = _terminal(d_terminal, di_)
    q, _ = _modified(tt, qi_, di_, b_, dt)
    ts = _switch_time(di_, b_, dt) if dt is not None else 0.0
    return make_record(
        method="dca.arps_rate",
        method_reference=REF_ARPS,
        maturity="M2",
        values={"q": q, "switch_time": ts},
        units={"q": "rate unit of qi", "switch_time": tu},
        scalar_inputs={
            "qi": qi_,
            "di": di_,
            "b": b_,
            "time_unit": tu,
            "d_terminal": "none" if dt is None else dt,
        },
        array_inputs={"t": tt},
        assumptions=("A-008", "A-010", "A-011"),
        warnings=_b_warnings(b_) + _terminal_warnings(di_, dt),
    )


def arps_cumulative(
    t: ArrayLike,
    *,
    qi: float,
    di: float,
    b: float,
    time_unit: TimeUnit,
    d_terminal: float | None,
) -> CalculationRecord:
    """Arps cumulative production Np(t) in closed form (optionally modified hyperbolic).

    Parameters are as in :func:`arps_rate`.

    Returns
    -------
    CalculationRecord
        ``np`` = ∫₀ᵗ q dt, in (rate unit of ``qi``) × ``time_unit``.

    Notes
    -----
    Maturity: M2 — verified against numerical quadrature of q(t). Assumptions: A-008,
    A-010, A-011.
    """
    tt = as_1d_array("t", t)
    _check_times(tt)
    qi_ = check_positive_scalar("qi", qi)
    di_ = check_positive_scalar("di", di)
    b_ = _b(b)
    tu = _time_unit(time_unit)
    dt = _terminal(d_terminal, di_)
    _, cum = _modified(tt, qi_, di_, b_, dt)
    return make_record(
        method="dca.arps_cumulative",
        method_reference=REF_ARPS,
        maturity="M2",
        values={"np": cum},
        units={"np": f"rate unit of qi x {tu}"},
        scalar_inputs={
            "qi": qi_,
            "di": di_,
            "b": b_,
            "time_unit": tu,
            "d_terminal": "none" if dt is None else dt,
        },
        array_inputs={"t": tt},
        assumptions=("A-008", "A-010", "A-011"),
        warnings=_b_warnings(b_) + _terminal_warnings(di_, dt),
    )


def arps_eur(
    *,
    qi: float,
    di: float,
    b: float,
    time_unit: TimeUnit,
    d_terminal: float | None,
    q_limit: float | None,
    t_horizon: float | None,
) -> CalculationRecord:
    """Estimated ultimate recovery to an economic rate limit and/or a time horizon.

    At least one of ``q_limit`` and ``t_horizon`` must be given; if both, the earlier
    cut-off applies.

    Parameters
    ----------
    qi, di, b, time_unit, d_terminal
        As in :func:`arps_rate`. For b >= 1 a ``d_terminal`` is **required** (A-012).
    q_limit : float or None
        Economic limit rate (> 0, < qi), same unit as ``qi``.
    t_horizon : float or None
        Time horizon in ``time_unit`` (> 0).

    Returns
    -------
    CalculationRecord
        ``eur`` (rate unit × time unit), ``t_end`` (``time_unit``) and ``q_end``.

    Raises
    ------
    InputValidationError
        Neither cut-off given, invalid values, or b >= 1 without ``d_terminal``.

    Notes
    -----
    Maturity: M2. Assumptions: A-010, A-011, A-012.
    """
    qi_ = check_positive_scalar("qi", qi)
    di_ = check_positive_scalar("di", di)
    b_ = _b(b)
    tu = _time_unit(time_unit)
    dt = _terminal(d_terminal, di_)
    if q_limit is None and t_horizon is None:
        raise InputValidationError(
            "q_limit and t_horizon: received None for both; expected at least one cut-off"
        )
    if b_ >= 1.0 and dt is None:
        raise InputValidationError(
            f"d_terminal: received None with b = {b_}; for b >= 1 the cumulative is unbounded "
            "in time and EUR requires a terminal decline (modified hyperbolic) (A-012)"
        )
    t_candidates: list[float] = []
    if t_horizon is not None:
        t_candidates.append(check_positive_scalar("t_horizon", t_horizon))
    if q_limit is not None:
        ql = check_positive_scalar("q_limit", q_limit)
        if ql >= qi_:
            raise InputValidationError(
                f"q_limit: received {ql!r} with qi = {qi_!r}; expected q_limit < qi"
            )
        t_candidates.append(_time_to_rate(ql, qi_, di_, b_, dt))
    t_end = min(t_candidates)
    q_end, cum = _modified(np.array([t_end]), qi_, di_, b_, dt)
    return make_record(
        method="dca.arps_eur",
        method_reference=REF_ARPS,
        maturity="M2",
        values={"eur": float(cum[0]), "t_end": t_end, "q_end": float(q_end[0])},
        units={"eur": f"rate unit of qi x {tu}", "t_end": tu, "q_end": "rate unit of qi"},
        scalar_inputs={
            "qi": qi_,
            "di": di_,
            "b": b_,
            "time_unit": tu,
            "d_terminal": "none" if dt is None else dt,
            "q_limit": "none" if q_limit is None else float(q_limit),
            "t_horizon": "none" if t_horizon is None else float(t_horizon),
        },
        array_inputs={},
        assumptions=("A-010", "A-011", "A-012"),
        warnings=_b_warnings(b_),
    )


def _time_to_rate(ql: float, qi: float, di: float, b: float, dt: float | None) -> float:
    """Invert q(t) = ql (closed form, including the terminal segment)."""
    if dt is not None and (b < B_EXP_THRESHOLD or dt >= di):
        return float(np.log(qi / ql) / max(di, dt))
    if b < B_EXP_THRESHOLD:
        return float(np.log(qi / ql) / di)
    t_hyp = float(np.expm1(b * np.log(qi / ql)) / (b * di))
    if dt is None:
        return t_hyp
    ts = _switch_time(di, b, dt)
    if t_hyp <= ts:
        return t_hyp
    qs = float(_rate(np.array([ts]), qi, di, b)[0])
    return ts + float(np.log(qs / ql) / dt)


def nominal_to_effective_decline(d_nominal: ArrayLike, *, b: float) -> CalculationRecord:
    """Effective decline over one period from the nominal decline per that period.

    b = 0 gives the (tangent) effective decline ``1 − exp(−D)``; b > 0 gives the
    **secant** effective decline ``1 − (1 + b·D)^(−1/b)`` (SPEE REP #6), i.e.
    ``1 − q(1 period)/qi`` for an Arps hyperbola.

    Parameters
    ----------
    d_nominal : array_like
        Nominal decline per period (> 0, fraction, e.g. 0.30 for 30 %/period).
    b : float
        Hyperbolic exponent in [0, 2].

    Returns
    -------
    CalculationRecord
        ``d_effective`` (fraction per period).

    Notes
    -----
    Maturity: M3 — reproduces SPEE REP #6 Table 1 (VAL-DCA-L01). Assumptions: A-008, A-011.
    """
    d = as_1d_array("d_nominal", d_nominal)
    _positive_array("d_nominal", d)
    b_ = _b(b)
    if b_ < B_EXP_THRESHOLD:
        de = -np.expm1(-d)
    else:
        de = -np.expm1(-np.log1p(b_ * d) / b_)
    return make_record(
        method="dca.nominal_to_effective_decline",
        method_reference=REF_SPEE,
        maturity="M3",
        values={"d_effective": de},
        units={"d_effective": "fraction per period"},
        scalar_inputs={"b": b_},
        array_inputs={"d_nominal": d},
        assumptions=("A-008", "A-011"),
    )


def effective_to_nominal_decline(d_effective: ArrayLike, *, b: float) -> CalculationRecord:
    """Inverse of :func:`nominal_to_effective_decline`.

    b = 0: ``D = −ln(1 − De)``; b > 0: ``D = ((1 − De)^(−b) − 1)/b``.

    Parameters
    ----------
    d_effective : array_like
        Effective decline per period, fraction in (0, 1).
    b : float
        Hyperbolic exponent in [0, 2].

    Notes
    -----
    Maturity: M2 (round-trip with the M3 forward conversion). Assumptions: A-008, A-011.
    """
    de = as_1d_array("d_effective", d_effective)
    bad = np.flatnonzero((de <= 0.0) | (de >= 1.0))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"d_effective[{i}]: received {de[i]!r}; expected a fraction in (0, 1)"
        )
    b_ = _b(b)
    if b_ < B_EXP_THRESHOLD:
        d = -np.log1p(-de)
    else:
        d = np.expm1(-b_ * np.log1p(-de)) / b_
    return make_record(
        method="dca.effective_to_nominal_decline",
        method_reference=REF_SPEE,
        maturity="M2",
        values={"d_nominal": d},
        units={"d_nominal": "fraction per period"},
        scalar_inputs={"b": b_},
        array_inputs={"d_effective": de},
        assumptions=("A-008", "A-011"),
    )


def convert_nominal_decline(
    d_nominal: ArrayLike, *, from_unit: TimeUnit, to_unit: TimeUnit
) -> CalculationRecord:
    """Convert a nominal (instantaneous) decline between time units.

    Nominal declines scale linearly with the time unit: D_per_year = 12·D_per_month =
    365.25·D_per_day (A-010). Effective declines do **not** scale this way.

    Notes
    -----
    Maturity: M2. Assumptions: A-008, A-010.
    """
    d = as_1d_array("d_nominal", d_nominal)
    _positive_array("d_nominal", d)
    fu, tu = _time_unit(from_unit), _time_unit(to_unit)
    out = d * DAYS_PER[tu] / DAYS_PER[fu]
    return make_record(
        method="dca.convert_nominal_decline",
        method_reference=REF_SPEE,
        maturity="M2",
        values={"d_nominal": out},
        units={"d_nominal": f"1/{tu}"},
        scalar_inputs={"from_unit": fu, "to_unit": tu},
        array_inputs={"d_nominal_in": d},
        assumptions=("A-008", "A-010"),
    )


def _positive_array(name: str, arr: NDArray[np.float64]) -> None:
    bad = np.flatnonzero(arr <= 0.0)
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(f"{name}[{i}]: received {arr[i]!r}; expected a value > 0")


# --------------------------------------------------------------------------- fitting
MIN_POINTS: Final[int] = 4
MAX_CONDITION: Final[float] = 1e12


def arps_fit(
    t: ArrayLike,
    q: ArrayLike,
    *,
    include: ArrayLike,
    time_unit: TimeUnit,
) -> CalculationRecord:
    """Fit qi, Di, b of a pure Arps hyperbola by bounded nonlinear least squares.

    Residuals are ``ln q_model − ln q_obs`` on the included points (A-013), solved with
    ``scipy.optimize.least_squares`` (trust-region reflective) with bounds qi > 0,
    Di > 0, 0 <= b <= 2.

    Parameters
    ----------
    t : array_like
        Time in ``time_unit`` (>= 0, strictly increasing).
    q : array_like
        Observed rate (any unit), same length as ``t``.
    include : array_like of bool
        Explicit mask of points used in the fit (shut-ins and outliers must be excluded
        here). Included points must have q > 0.
    time_unit : {"day", "month", "year"}

    Returns
    -------
    CalculationRecord
        ``qi``, ``di``, ``b`` and their standard errors ``*_se`` (from the Jacobian,
        s²·(JᵀJ)⁻¹), ``rmse`` and ``r2`` (in rate space, included points), ``converged``
        (1/0), ``nfev``, ``n_points`` and ``q_fitted`` (evaluated at all t, including
        excluded points, for diagnostics).

    Raises
    ------
    InputValidationError
        Bad shapes, non-bool mask, included q <= 0, t not strictly increasing.
    IdentifiabilityError
        Fewer than 4 included points, or ill-conditioned Jacobian (cond > 1e12).

    Notes
    -----
    Maturity: M2 — recovers parameters of exact and noisy synthetic curves (seeded).
    Assumptions: A-008, A-010, A-011, A-013.
    """
    tt = as_1d_array("t", t)
    qq = as_1d_array("q", q)
    check_same_length(t=tt, q=qq)
    _check_times(tt)
    if np.any(np.diff(tt) <= 0.0):
        raise InputValidationError("t: expected strictly increasing times")
    mask_raw = np.asarray(include)
    if mask_raw.dtype != np.bool_ or mask_raw.shape != tt.shape:
        raise InputValidationError(
            f"include: received dtype {mask_raw.dtype} shape {mask_raw.shape}; "
            f"expected a bool array of shape {tt.shape}"
        )
    mask = mask_raw.copy()
    tu = _time_unit(time_unit)
    bad = np.flatnonzero(mask & (qq <= 0.0))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"q[{i}]: received {qq[i]!r} on an included point; expected q > 0 "
            "(exclude shut-ins and zero rates with the include mask)"
        )
    n = int(mask.sum())
    if n < MIN_POINTS:
        raise IdentifiabilityError(
            f"include: {n} point(s) selected; at least {MIN_POINTS} are needed to fit 3 "
            "parameters with residual degrees of freedom"
        )
    ti, qo = tt[mask], qq[mask]
    lnq = np.log(qo)

    def resid(p: NDArray[np.float64]) -> NDArray[np.float64]:
        lnqi, di, b = p
        bb = max(b, 0.0)
        if bb < B_EXP_THRESHOLD:
            model = lnqi - di * ti
        else:
            model = lnqi - np.log1p(bb * di * ti) / bb
        r: NDArray[np.float64] = model - lnq
        return r

    # initial guess: exponential through first and last included points
    span = max(float(ti[-1] - ti[0]), 1e-12)
    d0 = max(float(lnq[0] - lnq[-1]) / span, 1e-6)
    x0 = np.array([float(lnq[0]) + d0 * float(ti[0]), d0, 0.5])
    lower = np.array([-np.inf, 1e-12, 0.0])
    upper = np.array([np.inf, np.inf, B_MAX])
    res = least_squares(
        resid, x0, bounds=(lower, upper), method="trf", x_scale="jac", max_nfev=2000
    )
    lnqi, di, b = (float(v) for v in res.x)
    qi = float(np.exp(lnqi))
    jac = np.asarray(res.jac, dtype=np.float64)
    cond = float(np.linalg.cond(jac))
    if not np.isfinite(cond) or cond > MAX_CONDITION:
        raise IdentifiabilityError(
            f"Jacobian condition number {cond:.3e} exceeds {MAX_CONDITION:.0e}: the "
            "parameters are not identifiable from these data (e.g. too short a decline)"
        )
    dof = n - 3
    s2 = float(np.sum(res.fun**2)) / dof
    cov = s2 * np.linalg.inv(jac.T @ jac)
    se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    q_fit = _rate(tt, qi, di, b)
    q_fit_in = q_fit[mask]
    rmse = float(np.sqrt(np.mean((q_fit_in - qo) ** 2)))
    ss_tot = float(np.sum((qo - qo.mean()) ** 2))
    r2 = 1.0 - float(np.sum((q_fit_in - qo) ** 2)) / ss_tot if ss_tot > 0 else 1.0
    warnings = _b_warnings(b)
    if b <= 1e-8 or b >= B_MAX - 1e-8:
        warnings.append(
            CalcWarning("B_AT_BOUND", f"fitted b = {b} lies on the bound [0, {B_MAX}]")
        )
    if not res.success:
        warnings.append(CalcWarning("NOT_CONVERGED", f"least_squares: {res.message}"))
    if not np.all(np.isfinite(q_fit)):
        raise NumericalError("arps_fit: fitted curve is not finite")
    excluded = np.flatnonzero(~mask)
    if excluded.size:
        warnings.append(
            CalcWarning(
                "POINTS_EXCLUDED",
                f"{excluded.size} point(s) excluded by the include mask",
                tuple(int(i) for i in excluded),
            )
        )
    return make_record(
        method="dca.arps_fit",
        method_reference=REF_ARPS,
        maturity="M2",
        values={
            "qi": qi,
            "di": di,
            "b": b,
            # se of qi by the delta method from the ln(qi) parameterisation
            "qi_se": qi * float(se[0]),
            "di_se": float(se[1]),
            "b_se": float(se[2]),
            "rmse": rmse,
            "r2": r2,
            "converged": int(res.success),
            "nfev": int(res.nfev),
            "n_points": n,
            "q_fitted": q_fit,
        },
        units={
            "qi": "rate unit of q",
            "di": f"1/{tu}",
            "b": "dimensionless",
            "qi_se": "rate unit of q",
            "di_se": f"1/{tu}",
            "b_se": "dimensionless",
            "rmse": "rate unit of q",
            "r2": "dimensionless",
            "converged": "flag",
            "nfev": "count",
            "n_points": "count",
            "q_fitted": "rate unit of q",
        },
        scalar_inputs={"time_unit": tu},
        array_inputs={"t": tt, "q": qq, "include": mask.astype(np.float64)},
        assumptions=("A-008", "A-010", "A-011", "A-013"),
        warnings=warnings,
    )
