"""Bourdet pressure derivative for well-test analysis (drawdown / flowing time).

With X = ln Δt, the derivative at point i uses the nearest point j on the left with
X_i − X_j >= L and the nearest point k on the right with X_k − X_i >= L:

    dΔp/dX|_i = [ (Δp_ij/ΔX_ij)·ΔX_ik + (Δp_ik/ΔX_ik)·ΔX_ij ] / (ΔX_ij + ΔX_ik)

L is a distance in **natural-log** units (typically 0.1–0.5), not a number of points.
Where no qualifying neighbour exists on one side (start/end of the record), a one-sided
difference is used and flagged. Superposition (buildup) time is not implemented (M0).

Maturity: M2
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import ArrayLike

from georeservoir.common.exceptions import InputValidationError, NumericalError
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.units import PressureUnit
from georeservoir.common.validation import (
    as_1d_array,
    check_positive_scalar,
    check_same_length,
    check_strictly_increasing,
    require_finite_scalar,
)

__all__ = ["bourdet_derivative"]

REF_BOURDET: Final[str] = (
    "Bourdet, D., Ayoub, J.A. & Pirard, Y.M. (1989), Use of Pressure Derivative in "
    "Well-Test Interpretation, SPE Formation Evaluation 4(2), SPE-12777-PA"
)
_PRESSURE_UNITS: Final[tuple[str, ...]] = ("Pa", "kPa", "MPa", "psi", "bar")


def bourdet_derivative(
    dt: ArrayLike,
    dp: ArrayLike,
    *,
    window_ln: float,
    sigma_p: float,
    pressure_unit: PressureUnit,
) -> CalculationRecord:
    """Bourdet derivative dΔp/d(ln Δt) in flowing (drawdown) time.

    Parameters
    ----------
    dt : array_like
        Elapsed time since the rate change, any time unit (> 0, strictly increasing;
        duplicates are refused). The derivative is independent of the time unit.
    dp : array_like
        Pressure change Δp, ``pressure_unit``; same length as ``dt`` (>= 3 points).
    window_ln : float
        Smoothing distance L in natural-log units of time (> 0). L = 0 is not allowed;
        the smallest L that still selects neighbours is any value below the minimum
        log-spacing.
    sigma_p : float
        Standard deviation of the independent pressure error per point, ``pressure_unit``
        (>= 0), propagated linearly to the derivative.
    pressure_unit : {"Pa", "kPa", "MPa", "psi", "bar"}

    Returns
    -------
    CalculationRecord
        ``derivative`` (``pressure_unit``), ``sigma_derivative`` (``pressure_unit``) and
        ``side`` (0 = central, −1 = backward only, +1 = forward only).

    Raises
    ------
    InputValidationError
        Non-finite values, < 3 points, non-positive or non-increasing time, L <= 0,
        sigma_p < 0, unknown unit.
    NumericalError
        Some point has no neighbour at distance >= L on either side (record shorter than L).

    Notes
    -----
    Maturity: M2. Exact for Δp linear in ln t; for Δp ∝ t with uniform log spacing equal
    to L it returns Δp·sinh(L)/L (smoothing bias L²/6, tested). Assumptions: A-008, A-016.
    """
    t = as_1d_array("dt", dt, min_size=3)
    p = as_1d_array("dp", dp, min_size=3)
    check_same_length(dt=t, dp=p)
    bad = np.flatnonzero(t <= 0.0)
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(f"dt[{i}]: received {t[i]!r}; expected dt > 0")
    check_strictly_increasing("dt", t)
    L = check_positive_scalar("window_ln", window_ln)
    sp = require_finite_scalar("sigma_p", sigma_p)
    if sp < 0.0:
        raise InputValidationError(f"sigma_p: received {sp!r}; expected sigma_p >= 0")
    if not isinstance(pressure_unit, str) or pressure_unit not in _PRESSURE_UNITS:
        raise InputValidationError(
            f"pressure_unit: received {pressure_unit!r}; expected one of {list(_PRESSURE_UNITS)}"
        )

    x = np.log(t)
    n = x.size
    idx = np.arange(n)
    # nearest left point with x_j <= x_i − L, nearest right point with x_k >= x_i + L;
    # a relative slack of 1e-9·L absorbs rounding when the log spacing equals L (A-016)
    slack = 1e-9 * L
    j = np.searchsorted(x, x - L + slack, side="right") - 1
    k = np.searchsorted(x, x + L - slack, side="left")
    has_j = j >= 0
    has_k = k < n
    none = np.flatnonzero(~has_j & ~has_k)
    if none.size:
        raise NumericalError(
            f"dt: point {int(none[0])} has no neighbour at log-distance >= {L} on either "
            f"side; the record spans only {x[-1] - x[0]:.4g} in ln t (reduce window_ln)"
        )
    jj = np.where(has_j, j, idx)
    kk = np.where(has_k, k, idx)
    a = x - x[jj]  # ΔX_ij (0 where missing)
    c = x[kk] - x  # ΔX_ik (0 where missing)

    deriv = np.empty(n)
    w_j = np.zeros(n)
    w_i = np.zeros(n)
    w_k = np.zeros(n)
    both = has_j & has_k
    left = has_j & ~has_k
    right = ~has_j & has_k

    ab, cb = a[both], c[both]
    s = ab + cb
    w_j[both] = -cb / (ab * s)
    w_k[both] = ab / (cb * s)
    w_i[both] = cb / (ab * s) - ab / (cb * s)
    w_j[left] = -1.0 / a[left]
    w_i[left] = 1.0 / a[left]
    w_i[right] = -1.0 / c[right]
    w_k[right] = 1.0 / c[right]
    deriv = w_j * p[jj] + w_i * p + w_k * p[kk]
    sigma = sp * np.sqrt(w_j**2 + w_i**2 + w_k**2)
    side = np.where(both, 0.0, np.where(left, -1.0, 1.0))

    warnings: list[CalcWarning] = []
    one = np.flatnonzero(~both)
    if one.size:
        warnings.append(
            CalcWarning(
                "ONE_SIDED_DERIVATIVE",
                f"{one.size} point(s) near the ends of the record use a one-sided difference "
                "(less smoothing, higher noise)",
                tuple(int(i) for i in one),
            )
        )
    return make_record(
        method="bourdet.bourdet_derivative",
        method_reference=REF_BOURDET,
        maturity="M2",
        values={"derivative": deriv, "sigma_derivative": sigma, "side": side},
        units={"derivative": pressure_unit, "sigma_derivative": pressure_unit, "side": "flag"},
        scalar_inputs={"window_ln": L, "sigma_p": sp, "pressure_unit": pressure_unit},
        array_inputs={"dt": t, "dp": p},
        assumptions=("A-008", "A-016"),
        warnings=warnings,
    )
