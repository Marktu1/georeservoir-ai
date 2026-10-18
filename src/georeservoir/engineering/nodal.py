"""Nodal analysis: inflow (IPR), tabulated outflow (TPR) and operating-point solver.

Conventions
-----------
* All pressures of one calculation share the declared ``pressure_unit`` (gauge or
  absolute is the caller's choice, but must be consistent). IPR equations depend only on
  pressure ratios and differences, so they are evaluated in that unit (A-014).
* Rates are in any rate unit; ``j`` is in rate unit per ``pressure_unit``.
* IPR models: linear (single-phase), Vogel (saturated, p̄r <= pb) and composite
  (undersaturated, p̄r > pb: linear above pb, Vogel-type below).
* TPR: only a user-supplied table, interpolated with a monotone piecewise-cubic Hermite
  interpolant (PCHIP). Multiphase correlations are M0 (planned) and raise errors.

Maturity: ``ipr_linear``, ``ipr_vogel`` and ``vogel_qmax_from_test`` M3 (Vogel 1968
worked example); ``ipr_composite`` M3 from university lecture notes only (weaker source,
see docs/validation/nodal.md); other functions M2; multiphase correlations M0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Protocol

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq

from georeservoir.common.exceptions import (
    InputValidationError,
    NumericalError,
    PhysicalConsistencyError,
)
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.units import PressureUnit
from georeservoir.common.validation import (
    as_1d_array,
    check_positive_scalar,
    check_same_length,
    check_strictly_increasing,
)

__all__ = [
    "CompositeIPR",
    "IPRModel",
    "LinearIPR",
    "TPRModel",
    "TabulatedTPR",
    "VogelIPR",
    "beggs_brill_tpr",
    "composite_j_from_test",
    "hagedorn_brown_tpr",
    "ipr_composite",
    "ipr_linear",
    "ipr_vogel",
    "nodal_solve",
    "vogel_qmax_from_test",
]

REF_VOGEL: Final[str] = (
    "Vogel, J.V. (1968), Inflow Performance Relationships for Solution-Gas Drive Wells, "
    "Journal of Petroleum Technology 20(1), SPE-1476-PA"
)
REF_COMPOSITE: Final[str] = (
    "Composite (generalized Vogel) IPR: linear above pb, Vogel below; e.g. Beggs, H.D. "
    "(1991), Production Optimization Using Nodal Analysis, OGCI"
)
REF_LINEAR: Final[str] = (
    "Single-phase productivity index, q = J (p̄r − pwf); compared with Vogel's IPR in "
    "Vogel (1968), SPE-1476"
)
REF_NODAL: Final[str] = (
    "Nodal (systems) analysis: intersection of inflow and outflow curves; e.g. Beggs (1991), "
    "Production Optimization Using Nodal Analysis, OGCI"
)
_PRESSURE_UNITS: Final[tuple[str, ...]] = ("Pa", "kPa", "MPa", "psi", "bar")


def _unit(u: str) -> str:
    if not isinstance(u, str) or u not in _PRESSURE_UNITS:
        raise InputValidationError(
            f"pressure_unit: received {u!r}; expected one of {list(_PRESSURE_UNITS)}"
        )
    return u


def _check_pwf(pwf: NDArray[np.float64], p_res: float) -> None:
    bad = np.flatnonzero((pwf < 0.0) | (pwf > p_res))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"pwf[{i}]: received {pwf[i]!r}; expected a value in [0, p_res = {p_res!r}]"
        )


def _check_q(q: NDArray[np.float64], q_max: float) -> None:
    bad = np.flatnonzero((q < 0.0) | (q > q_max))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"q[{i}]: received {q[i]!r}; expected a value in [0, q_max = {q_max!r}]"
        )


# --------------------------------------------------------------------------- IPR models
class IPRModel(Protocol):
    """Inflow model: rate from bottomhole pressure and its inverse."""

    @property
    def p_res(self) -> float: ...

    @property
    def q_max(self) -> float: ...

    def rate(self, pwf: NDArray[np.float64]) -> NDArray[np.float64]: ...

    def pwf(self, q: NDArray[np.float64]) -> NDArray[np.float64]: ...


@dataclass(frozen=True, slots=True)
class LinearIPR:
    """q = J·(p̄r − pwf). Single-phase. Maturity: M2."""

    p_res: float
    j: float

    def __post_init__(self) -> None:
        check_positive_scalar("p_res", self.p_res)
        check_positive_scalar("j", self.j)

    @property
    def q_max(self) -> float:
        return self.j * self.p_res

    def rate(self, pwf: NDArray[np.float64]) -> NDArray[np.float64]:
        out: NDArray[np.float64] = self.j * (self.p_res - pwf)
        return out

    def pwf(self, q: NDArray[np.float64]) -> NDArray[np.float64]:
        _check_q(q, self.q_max)
        out: NDArray[np.float64] = self.p_res - q / self.j
        return out


def _vogel_ratio_inverse(y: NDArray[np.float64]) -> NDArray[np.float64]:
    """Solve 1 − 0.2x − 0.8x² = y for x in [0, 1] (y in [0, 1])."""
    out: NDArray[np.float64] = (-0.2 + np.sqrt(0.04 + 3.2 * (1.0 - y))) / 1.6
    return out


@dataclass(frozen=True, slots=True)
class VogelIPR:
    """q/qmax = 1 − 0.2·(pwf/p̄r) − 0.8·(pwf/p̄r)². Saturated reservoir. Maturity: M3."""

    p_res: float
    aof: float  # absolute open flow, rate at pwf = 0

    def __post_init__(self) -> None:
        check_positive_scalar("p_res", self.p_res)
        check_positive_scalar("aof", self.aof)

    @property
    def q_max(self) -> float:
        return self.aof

    def rate(self, pwf: NDArray[np.float64]) -> NDArray[np.float64]:
        x = pwf / self.p_res
        out: NDArray[np.float64] = self.aof * (1.0 - 0.2 * x - 0.8 * x * x)
        return out

    def pwf(self, q: NDArray[np.float64]) -> NDArray[np.float64]:
        _check_q(q, self.q_max)
        out: NDArray[np.float64] = self.p_res * _vogel_ratio_inverse(q / self.aof)
        return out


@dataclass(frozen=True, slots=True)
class CompositeIPR:
    """Undersaturated (p̄r > pb): linear above pb; below, q = qb + (J·pb/1.8)·V(pwf/pb).

    V(x) = 1 − 0.2x − 0.8x², qb = J(p̄r − pb). q and dq/dpwf are continuous at pb.
    Maturity: M3.
    """

    p_res: float
    p_bubble: float
    j: float

    def __post_init__(self) -> None:
        check_positive_scalar("p_res", self.p_res)
        check_positive_scalar("p_bubble", self.p_bubble)
        check_positive_scalar("j", self.j)
        if self.p_bubble >= self.p_res:
            raise PhysicalConsistencyError(
                f"p_bubble: received {self.p_bubble!r} with p_res = {self.p_res!r}; the "
                "composite IPR needs p_res > p_bubble (use the Vogel IPR when saturated)"
            )

    @property
    def q_b(self) -> float:
        return self.j * (self.p_res - self.p_bubble)

    @property
    def _qv(self) -> float:
        return self.j * self.p_bubble / 1.8

    @property
    def q_max(self) -> float:
        return self.q_b + self._qv

    def rate(self, pwf: NDArray[np.float64]) -> NDArray[np.float64]:
        x = pwf / self.p_bubble
        below = self.q_b + self._qv * (1.0 - 0.2 * x - 0.8 * x * x)
        above = self.j * (self.p_res - pwf)
        out: NDArray[np.float64] = np.where(pwf >= self.p_bubble, above, below)
        return out

    def pwf(self, q: NDArray[np.float64]) -> NDArray[np.float64]:
        _check_q(q, self.q_max)
        above = self.p_res - q / self.j
        y = np.clip((q - self.q_b) / self._qv, 0.0, 1.0)  # only used where q > qb
        below = self.p_bubble * _vogel_ratio_inverse(y)
        out: NDArray[np.float64] = np.where(q <= self.q_b, above, below)
        return out


def _ipr_record(
    method: str,
    reference: str,
    maturity: str,
    model: IPRModel,
    pwf: NDArray[np.float64],
    unit: str,
    scalars: dict[str, float | str],
    extra: dict[str, float] | None = None,
) -> CalculationRecord:
    values: dict[str, NDArray[np.float64] | float] = {"q": model.rate(pwf), "q_max": model.q_max}
    units = {"q": "rate unit", "q_max": "rate unit"}
    for k, v in (extra or {}).items():
        values[k] = v
        units[k] = "rate unit"
    return make_record(
        method=method,
        method_reference=reference,
        maturity=maturity,  # type: ignore[arg-type]
        values=values,
        units=units,
        scalar_inputs={**scalars, "pressure_unit": unit},
        array_inputs={"pwf": pwf},
        assumptions=("A-008", "A-014"),
    )


def ipr_linear(
    pwf: ArrayLike, *, p_res: float, j: float, pressure_unit: PressureUnit
) -> CalculationRecord:
    """Single-phase IPR, q = J·(p̄r − pwf), for pwf in [0, p̄r].

    Parameters
    ----------
    pwf : array_like
        Flowing bottomhole pressure, ``pressure_unit``.
    p_res : float
        Average reservoir pressure, ``pressure_unit`` (> 0).
    j : float
        Productivity index, rate unit per ``pressure_unit`` (> 0).
    pressure_unit : {"Pa", "kPa", "MPa", "psi", "bar"}

    Returns
    -------
    CalculationRecord
        ``q`` and ``q_max`` (= J·p̄r).

    Notes
    -----
    Maturity: M3 — reproduces the straight-line PI comparison in Vogel (1968)
    (VAL-ND-L06). Single-phase only. Assumptions: A-008, A-014.
    """
    u = _unit(pressure_unit)
    model = LinearIPR(p_res, j)
    p = as_1d_array("pwf", pwf)
    _check_pwf(p, model.p_res)
    return _ipr_record(
        "nodal.ipr_linear", REF_LINEAR, "M3", model, p, u, {"p_res": float(p_res), "j": float(j)}
    )


def ipr_vogel(
    pwf: ArrayLike, *, p_res: float, q_max: float, pressure_unit: PressureUnit
) -> CalculationRecord:
    """Vogel IPR for a saturated reservoir (p̄r <= pb).

    Parameters
    ----------
    pwf : array_like
        Flowing bottomhole pressure in [0, p̄r], ``pressure_unit``.
    p_res : float
        Average reservoir pressure (> 0).
    q_max : float
        Absolute open flow (rate at pwf = 0), > 0. See :func:`vogel_qmax_from_test`.
    pressure_unit : {"Pa", "kPa", "MPa", "psi", "bar"}

    Notes
    -----
    Maturity: M3 — reproduces the worked example of Vogel (1968) (VAL-ND-L05) and a
    published lecture-note IPR table (VAL-ND-L01). Empirical: Vogel expects maximum errors
    of ~20 % (typically ~10 %) for solution-gas drive. Assumptions: A-008, A-014.
    """
    u = _unit(pressure_unit)
    model = VogelIPR(p_res, q_max)
    p = as_1d_array("pwf", pwf)
    _check_pwf(p, model.p_res)
    return _ipr_record(
        "nodal.ipr_vogel",
        REF_VOGEL,
        "M3",
        model,
        p,
        u,
        {"p_res": float(p_res), "q_max": float(q_max)},
    )


def vogel_qmax_from_test(
    *, p_res: float, q_test: float, pwf_test: float, pressure_unit: PressureUnit
) -> CalculationRecord:
    """Vogel AOF from one stabilised test: q_max = q_test / (1 − 0.2x − 0.8x²), x = pwf/p̄r.

    Raises
    ------
    InputValidationError
        pwf_test outside [0, p̄r) (a test at pwf = p̄r carries no rate information).

    Notes
    -----
    Maturity: M3 — reproduces (qo)max of the worked example in Vogel (1968)
    (VAL-ND-L04). Assumptions: A-014.
    """
    u = _unit(pressure_unit)
    pr = check_positive_scalar("p_res", p_res)
    qt = check_positive_scalar("q_test", q_test)
    pt = float(pwf_test)
    if not 0.0 <= pt < pr:
        raise InputValidationError(
            f"pwf_test: received {pt!r}; expected a value in [0, p_res = {pr!r})"
        )
    x = pt / pr
    qmax = qt / (1.0 - 0.2 * x - 0.8 * x * x)
    return make_record(
        method="nodal.vogel_qmax_from_test",
        method_reference=REF_VOGEL,
        maturity="M3",
        values={"q_max": qmax},
        units={"q_max": "rate unit"},
        scalar_inputs={"p_res": pr, "q_test": qt, "pwf_test": pt, "pressure_unit": u},
        array_inputs={},
        assumptions=("A-014",),
    )


def ipr_composite(
    pwf: ArrayLike, *, p_res: float, p_bubble: float, j: float, pressure_unit: PressureUnit
) -> CalculationRecord:
    """Composite IPR for an undersaturated reservoir (p̄r > pb).

    Parameters
    ----------
    pwf : array_like
        Flowing bottomhole pressure in [0, p̄r].
    p_res, p_bubble : float
        Average reservoir and bubble-point pressures (> 0, p_res > p_bubble).
    j : float
        Productivity index above the bubble point (> 0). See :func:`composite_j_from_test`.
    pressure_unit : {"Pa", "kPa", "MPa", "psi", "bar"}

    Returns
    -------
    CalculationRecord
        ``q``, ``q_max`` (= qb + J·pb/1.8) and ``q_b`` (rate at pwf = pb).

    Raises
    ------
    PhysicalConsistencyError
        p_bubble >= p_res.

    Notes
    -----
    Maturity: M3 — reproduces a published worked composite IPR table from lecture notes
    (VAL-ND-L02; weaker source, see docs/validation/nodal.md). Assumptions: A-008, A-014.
    """
    u = _unit(pressure_unit)
    model = CompositeIPR(p_res, p_bubble, j)
    p = as_1d_array("pwf", pwf)
    _check_pwf(p, model.p_res)
    return _ipr_record(
        "nodal.ipr_composite",
        REF_COMPOSITE,
        "M3",
        model,
        p,
        u,
        {"p_res": float(p_res), "p_bubble": float(p_bubble), "j": float(j)},
        extra={"q_b": model.q_b},
    )


def composite_j_from_test(
    *,
    p_res: float,
    p_bubble: float,
    q_test: float,
    pwf_test: float,
    pressure_unit: PressureUnit,
) -> CalculationRecord:
    """Productivity index J of the composite IPR from one stabilised test.

    Above pb: J = q/(p̄r − pwf). Below pb: J = q / [(p̄r − pb) + (pb/1.8)·V(pwf/pb)].

    Notes
    -----
    Maturity: M2. Assumptions: A-014.
    """
    u = _unit(pressure_unit)
    pr = check_positive_scalar("p_res", p_res)
    pb = check_positive_scalar("p_bubble", p_bubble)
    if pb >= pr:
        raise PhysicalConsistencyError(
            f"p_bubble: received {pb!r} with p_res = {pr!r}; expected p_res > p_bubble"
        )
    qt = check_positive_scalar("q_test", q_test)
    pt = float(pwf_test)
    if not 0.0 <= pt < pr:
        raise InputValidationError(
            f"pwf_test: received {pt!r}; expected a value in [0, p_res = {pr!r})"
        )
    if pt >= pb:
        j = qt / (pr - pt)
    else:
        x = pt / pb
        j = qt / ((pr - pb) + pb / 1.8 * (1.0 - 0.2 * x - 0.8 * x * x))
    return make_record(
        method="nodal.composite_j_from_test",
        method_reference=REF_COMPOSITE,
        maturity="M2",
        values={"j": j},
        units={"j": f"rate unit/{u}"},
        scalar_inputs={
            "p_res": pr,
            "p_bubble": pb,
            "q_test": qt,
            "pwf_test": pt,
            "pressure_unit": u,
        },
        array_inputs={},
        assumptions=("A-014",),
    )


# --------------------------------------------------------------------------- TPR
class TPRModel(Protocol):
    """Outflow model: required bottomhole pressure as a function of rate."""

    @property
    def q_min(self) -> float: ...

    @property
    def q_max(self) -> float: ...

    def pwf(self, q: NDArray[np.float64]) -> NDArray[np.float64]: ...

    def dpwf_dq(self, q: NDArray[np.float64]) -> NDArray[np.float64]: ...


@dataclass(frozen=True)
class TabulatedTPR:
    """User-supplied TPR table, interpolated with PCHIP (monotone where the data are).

    No extrapolation: rates outside [q_min, q_max] of the table are refused. Maturity: M2.

    Parameters
    ----------
    q : array_like
        Rates, strictly increasing, >= 0 (at least 2 points).
    pwf : array_like
        Required bottomhole pressure at each rate (> 0), same ``pressure_unit`` as the IPR.
    """

    q: NDArray[np.float64]
    pwf_table: NDArray[np.float64]
    _interp: PchipInterpolator = field(init=False, repr=False, compare=False)

    def __init__(self, q: ArrayLike, pwf: ArrayLike) -> None:
        qq = as_1d_array("q", q, min_size=2)
        pp = as_1d_array("pwf", pwf, min_size=2)
        check_same_length(q=qq, pwf=pp)
        check_strictly_increasing("q", qq)
        if qq[0] < 0.0:
            raise InputValidationError(f"q[0]: received {qq[0]!r}; expected q >= 0")
        bad = np.flatnonzero(pp <= 0.0)
        if bad.size:
            i = int(bad[0])
            raise InputValidationError(f"pwf[{i}]: received {pp[i]!r}; expected pwf > 0")
        qq.setflags(write=False)
        pp.setflags(write=False)
        object.__setattr__(self, "q", qq)
        object.__setattr__(self, "pwf_table", pp)
        object.__setattr__(self, "_interp", PchipInterpolator(qq, pp, extrapolate=False))

    @property
    def q_min(self) -> float:
        return float(self.q[0])

    @property
    def q_max(self) -> float:
        return float(self.q[-1])

    def _check(self, q: NDArray[np.float64]) -> None:
        bad = np.flatnonzero((q < self.q_min) | (q > self.q_max))
        if bad.size:
            i = int(bad[0])
            raise InputValidationError(
                f"q[{i}]: received {q[i]!r}; the TPR table covers [{self.q_min!r}, "
                f"{self.q_max!r}] and is not extrapolated"
            )

    def pwf(self, q: NDArray[np.float64]) -> NDArray[np.float64]:
        self._check(q)
        out: NDArray[np.float64] = np.asarray(self._interp(q), dtype=np.float64)
        return out

    def dpwf_dq(self, q: NDArray[np.float64]) -> NDArray[np.float64]:
        self._check(q)
        out: NDArray[np.float64] = np.asarray(self._interp(q, 1), dtype=np.float64)
        return out


def hagedorn_brown_tpr(*args: object, **kwargs: object) -> TPRModel:
    """Hagedorn & Brown (1965) multiphase TPR. **Maturity: M0 — not implemented.**

    Raises
    ------
    NotImplementedError
        Always. Use :class:`TabulatedTPR` with outflow data from a validated tool.
    """
    raise NotImplementedError(
        "hagedorn_brown_tpr is planned (M0) and not implemented in this version; supply "
        "outflow data with TabulatedTPR (see docs/roadmap.md)"
    )


def beggs_brill_tpr(*args: object, **kwargs: object) -> TPRModel:
    """Beggs & Brill (1973) multiphase TPR. **Maturity: M0 — not implemented.**

    Raises
    ------
    NotImplementedError
        Always. Use :class:`TabulatedTPR` with outflow data from a validated tool.
    """
    raise NotImplementedError(
        "beggs_brill_tpr is planned (M0) and not implemented in this version; supply "
        "outflow data with TabulatedTPR (see docs/roadmap.md)"
    )


# --------------------------------------------------------------------------- solver
def nodal_solve(
    ipr: IPRModel,
    tpr: TPRModel,
    *,
    pressure_unit: PressureUnit,
    n_grid: int,
    xtol: float,
    maxiter: int,
) -> CalculationRecord:
    """Find **all** intersections of IPR and TPR on their common rate range.

    f(q) = pwf_IPR(q) − pwf_TPR(q) is sampled on a uniform grid of ``n_grid`` points over
    [max(q_min_TPR, 0), min(q_max_TPR, q_max_IPR)]; each sign change is refined with
    Brent's method (``xtol``, ``maxiter``). An intersection is **stable** when
    df/dq < 0 there (a small rate increase makes the tubing need more pressure than the
    reservoir supplies), otherwise unstable.

    Parameters
    ----------
    ipr : IPRModel
        :class:`LinearIPR`, :class:`VogelIPR` or :class:`CompositeIPR`.
    tpr : TPRModel
        :class:`TabulatedTPR`.
    pressure_unit : {"Pa", "kPa", "MPa", "psi", "bar"}
        Common unit of IPR and TPR pressures (recorded).
    n_grid : int
        Grid points for bracketing (>= 10). Intersections closer than one grid step can
        be missed; a near-tangency raises a warning.
    xtol : float
        Absolute rate tolerance for Brent's method (> 0).
    maxiter : int
        Maximum Brent iterations (>= 1).

    Returns
    -------
    CalculationRecord
        ``q_op``, ``pwf_op`` and ``stable`` (1/0) arrays (possibly empty) and
        ``n_solutions``. Warnings: ``NO_INTERSECTION``, ``POSSIBLE_TANGENCY``,
        ``MULTIPLE_SOLUTIONS``.

    Raises
    ------
    InputValidationError
        Bad numerical settings or no overlapping rate range.
    NumericalError
        Brent's method failed to converge.

    Notes
    -----
    Maturity: M2. Assumptions: A-014, A-015.
    """
    u = _unit(pressure_unit)
    if not isinstance(n_grid, int) or n_grid < 10:
        raise InputValidationError(f"n_grid: received {n_grid!r}; expected an int >= 10")
    if not isinstance(maxiter, int) or maxiter < 1:
        raise InputValidationError(f"maxiter: received {maxiter!r}; expected an int >= 1")
    xt = check_positive_scalar("xtol", xtol)
    lo, hi = max(tpr.q_min, 0.0), min(tpr.q_max, ipr.q_max)
    if hi <= lo:
        raise InputValidationError(
            f"rate ranges do not overlap: TPR [{tpr.q_min!r}, {tpr.q_max!r}], "
            f"IPR [0, {ipr.q_max!r}]"
        )

    def f(q: float) -> float:
        a = np.array([q])
        return float(ipr.pwf(a)[0] - tpr.pwf(a)[0])

    grid = np.linspace(lo, hi, n_grid)
    fv = ipr.pwf(grid) - tpr.pwf(grid)
    roots: list[float] = []
    for k in range(n_grid - 1):
        a, b = fv[k], fv[k + 1]
        if a == 0.0:
            roots.append(float(grid[k]))
        elif a * b < 0.0:
            try:
                r = brentq(f, grid[k], grid[k + 1], xtol=xt, maxiter=maxiter)
            except RuntimeError as exc:
                raise NumericalError(
                    f"brentq did not converge in [{grid[k]!r}, {grid[k + 1]!r}] within "
                    f"{maxiter} iterations: {exc}"
                ) from exc
            roots.append(float(r))
    if fv[-1] == 0.0:
        roots.append(float(grid[-1]))

    warnings: list[CalcWarning] = []
    scale = float(np.max(np.abs(fv))) or 1.0
    if not roots:
        if tpr.q_max < ipr.q_max:
            msg = (
                f"no intersection within the TPR table range [{lo:.6g}, {hi:.6g}]; the "
                f"table ends before the IPR AOF ({ipr.q_max:.6g}), so an intersection at "
                "higher rate cannot be excluded — extend the table"
            )
        else:
            msg = (
                "IPR and TPR do not intersect on the common rate range: the well cannot "
                "flow at these conditions"
            )
        warnings.append(CalcWarning("NO_INTERSECTION", msg))
    # near-touches: interior local minima of |f| below 1e-3·max|f| without a sign change
    af = np.abs(fv)
    root_arr = np.array(roots)
    step = (hi - lo) / (n_grid - 1)
    for k in range(n_grid):
        left_ok = k == 0 or af[k] <= af[k - 1]
        right_ok = k == n_grid - 1 or af[k] <= af[k + 1]
        if not (left_ok and right_ok) or af[k] >= 1e-3 * scale:
            continue
        nb = [fv[i] for i in (k - 1, k + 1) if 0 <= i < n_grid]
        crosses = any(v * fv[k] < 0.0 for v in nb) or (
            fv[k] == 0.0 and len(nb) == 2 and nb[0] * nb[1] < 0.0
        )
        near_root = root_arr.size and np.min(np.abs(root_arr - grid[k])) < step
        if not crosses and not (near_root and fv[k] != 0.0):
            warnings.append(
                CalcWarning(
                    "POSSIBLE_TANGENCY",
                    f"|IPR − TPR| reaches {af[k]:.3g} near q = "
                    f"{grid[k]:.6g} without crossing; curves may be "
                    "tangent (refine n_grid)",
                    (k,),
                )
            )
    if roots and min(roots) <= 0.0:
        warnings.append(
            CalcWarning(
                "ZERO_RATE_INTERSECTION",
                "an intersection at q = 0: the well is at the no-flow limit there, not producing",
            )
        )
    if len(roots) > 1:
        warnings.append(
            CalcWarning(
                "MULTIPLE_SOLUTIONS",
                f"{len(roots)} intersections found; the stable one with "
                "the highest rate is normally the operating point",
            )
        )
    q_op = np.array(roots, dtype=np.float64)
    pwf_op = tpr.pwf(q_op) if q_op.size else np.array([], dtype=np.float64)
    h = 1e-6 * (hi - lo)
    stable = np.empty(q_op.size)
    for i, q in enumerate(q_op):
        qa, qb = max(q - h, lo), min(q + h, hi)
        dfdq = (f(qb) - f(qa)) / (qb - qa)
        stable[i] = 1.0 if dfdq < 0.0 else 0.0
    return make_record(
        method="nodal.nodal_solve",
        method_reference=REF_NODAL,
        maturity="M2",
        values={"q_op": q_op, "pwf_op": pwf_op, "stable": stable, "n_solutions": int(q_op.size)},
        units={"q_op": "rate unit", "pwf_op": u, "stable": "flag", "n_solutions": "count"},
        scalar_inputs={
            "pressure_unit": u,
            "n_grid": n_grid,
            "xtol": xt,
            "maxiter": maxiter,
            "ipr": repr(ipr),
            "q_lo": lo,
            "q_hi": hi,
        },
        array_inputs={
            "tpr_q": np.asarray(getattr(tpr, "q", grid), dtype=np.float64),
            "tpr_pwf": np.asarray(getattr(tpr, "pwf_table", fv), dtype=np.float64),
        },
        assumptions=("A-014", "A-015"),
        warnings=warnings,
    )
