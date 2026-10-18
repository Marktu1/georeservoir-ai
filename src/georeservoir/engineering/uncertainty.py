"""Monte Carlo uncertainty propagation with fixed seeds (Archie Sw and Arps EUR).

Conventions (A-019, A-020)
--------------------------
* **P90 / P50 / P10 follow the SPE-PRMS exceedance convention**: P90 is the value
  exceeded with 90 % probability (the 10th percentile, the *low* case) and P10 the value
  exceeded with 10 % probability (the 90th percentile, the *high* case). Output keys say
  so explicitly: ``p90_low``, ``p50``, ``p10_high``.
* Percentiles use the linear interpolation estimator (Hyndman & Fan type 7, NumPy
  default).
* Inputs are sampled **independently** (no correlation) with ``numpy.random.Generator``
  (PCG64) seeded by the mandatory ``seed``, in the fixed order of the arguments, so the
  same inputs + seed + library version give bit-identical results.
* The deterministic equations are the library's own (single source); this module only
  samples and summarises.

Maturity: M2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

import numpy as np
from numpy.typing import NDArray

from georeservoir.common.exceptions import InputValidationError
from georeservoir.common.record import CalculationRecord, CalcWarning, make_record
from georeservoir.common.validation import (
    check_positive_scalar,
    coerce_float_fields,
    require_bool,
    require_finite_scalar,
)
from georeservoir.engineering import dca as _dca
from georeservoir.engineering import petrophysics as _pp

__all__ = [
    "Distribution",
    "Fixed",
    "LogNormal",
    "Normal",
    "Triangular",
    "Uniform",
    "mc_archie_sw",
    "mc_arps_eur",
]

REF_MC: Final[str] = (
    "Monte Carlo propagation; P90/P50/P10 per SPE/WPC/AAPG/SPEE Petroleum Resources "
    "Management System (PRMS, 2018) exceedance convention"
)
MIN_SAMPLES: Final[int] = 100
MAX_SAMPLES: Final[int] = 10_000_000


class Distribution(Protocol):
    """An input distribution that can be sampled reproducibly."""

    def sample(self, rng: np.random.Generator, n: int) -> NDArray[np.float64]: ...

    def describe(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Fixed:
    """A deterministic value (no uncertainty)."""

    value: float

    def __post_init__(self) -> None:
        coerce_float_fields(self, "value")
        require_finite_scalar("value", self.value)

    def sample(self, rng: np.random.Generator, n: int) -> NDArray[np.float64]:
        return np.full(n, float(self.value))

    def describe(self) -> str:
        return f"Fixed({self.value!r})"


@dataclass(frozen=True, slots=True)
class Uniform:
    """Uniform on [low, high], low < high."""

    low: float
    high: float

    def __post_init__(self) -> None:
        coerce_float_fields(self, "low", "high")
        lo = require_finite_scalar("low", self.low)
        hi = require_finite_scalar("high", self.high)
        if hi <= lo:
            raise InputValidationError(
                f"Uniform: received low={lo!r}, high={hi!r}; expected low < high"
            )

    def sample(self, rng: np.random.Generator, n: int) -> NDArray[np.float64]:
        out: NDArray[np.float64] = rng.uniform(self.low, self.high, n)
        return out

    def describe(self) -> str:
        return f"Uniform({self.low!r}, {self.high!r})"


@dataclass(frozen=True, slots=True)
class Triangular:
    """Triangular with low <= mode <= high and low < high."""

    low: float
    mode: float
    high: float

    def __post_init__(self) -> None:
        coerce_float_fields(self, "low", "mode", "high")
        lo = require_finite_scalar("low", self.low)
        mo = require_finite_scalar("mode", self.mode)
        hi = require_finite_scalar("high", self.high)
        if not (lo <= mo <= hi and lo < hi):
            raise InputValidationError(
                f"Triangular: received ({lo!r}, {mo!r}, {hi!r}); "
                "expected low <= mode <= high and low < high"
            )

    def sample(self, rng: np.random.Generator, n: int) -> NDArray[np.float64]:
        out: NDArray[np.float64] = rng.triangular(self.low, self.mode, self.high, n)
        return out

    def describe(self) -> str:
        return f"Triangular({self.low!r}, {self.mode!r}, {self.high!r})"


@dataclass(frozen=True, slots=True)
class Normal:
    """Normal(mean, sd), optionally truncated to [low, high] by rejection (explicit)."""

    mean: float
    sd: float
    low: float | None
    high: float | None

    def __post_init__(self) -> None:
        coerce_float_fields(self, "mean", "sd", "low", "high")
        require_finite_scalar("mean", self.mean)
        check_positive_scalar("sd", self.sd)
        lo = -np.inf if self.low is None else require_finite_scalar("low", self.low)
        hi = np.inf if self.high is None else require_finite_scalar("high", self.high)
        if hi <= lo:
            raise InputValidationError(
                f"Normal: received low={lo!r}, high={hi!r}; expected low < high"
            )

    def sample(self, rng: np.random.Generator, n: int) -> NDArray[np.float64]:
        lo = -np.inf if self.low is None else self.low
        hi = np.inf if self.high is None else self.high
        out = np.empty(0)
        for _ in range(1000):
            draw = rng.normal(self.mean, self.sd, max(2 * (n - out.size), 64))
            out = np.concatenate((out, draw[(draw >= lo) & (draw <= hi)]))
            if out.size >= n:
                result: NDArray[np.float64] = out[:n]
                return result
        raise InputValidationError(
            f"Normal: truncation window [{lo!r}, {hi!r}] keeps too little probability mass"
        )

    def describe(self) -> str:
        return f"Normal({self.mean!r}, {self.sd!r}, low={self.low!r}, high={self.high!r})"


@dataclass(frozen=True, slots=True)
class LogNormal:
    """Log-normal with given median (> 0) and standard deviation of ln X (> 0)."""

    median: float
    sigma_ln: float

    def __post_init__(self) -> None:
        coerce_float_fields(self, "median", "sigma_ln")
        check_positive_scalar("median", self.median)
        check_positive_scalar("sigma_ln", self.sigma_ln)

    def sample(self, rng: np.random.Generator, n: int) -> NDArray[np.float64]:
        out: NDArray[np.float64] = rng.lognormal(np.log(self.median), self.sigma_ln, n)
        return out

    def describe(self) -> str:
        return f"LogNormal(median={self.median!r}, sigma_ln={self.sigma_ln!r})"


def _settings(n_samples: int, seed: int) -> None:
    if (
        isinstance(n_samples, bool)
        or not isinstance(n_samples, int)
        or not (MIN_SAMPLES <= n_samples <= MAX_SAMPLES)
    ):
        raise InputValidationError(
            f"n_samples: received {n_samples!r}; expected an int in [{MIN_SAMPLES}, {MAX_SAMPLES}]"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise InputValidationError(f"seed: received {seed!r}; expected an int >= 0")


def _summary(
    x: NDArray[np.float64],
) -> dict[str, float]:
    p10th, p50, p90th = np.percentile(x, [10.0, 50.0, 90.0])
    return {
        "p90_low": float(p10th),
        "p50": float(p50),
        "p10_high": float(p90th),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)),
        "se_mean": float(x.std(ddof=1) / np.sqrt(x.size)),
    }


def _sample_all(
    dists: dict[str, Distribution], n: int, seed: int
) -> dict[str, NDArray[np.float64]]:
    rng = np.random.default_rng(seed)
    out: dict[str, NDArray[np.float64]] = {}
    for name, d in dists.items():  # fixed argument order → reproducible streams
        if not hasattr(d, "sample"):
            raise InputValidationError(
                f"{name}: received {d!r}; expected a Distribution (Fixed, Uniform, "
                "Triangular, Normal, LogNormal)"
            )
        s = np.asarray(d.sample(rng, n), dtype=np.float64)
        if s.shape != (n,) or not np.all(np.isfinite(s)):
            raise InputValidationError(f"{name}: sampler returned invalid values")
        out[name] = s
    return out


def _record(
    method: str,
    key: str,
    unit: str,
    x: NDArray[np.float64],
    dists: dict[str, Distribution],
    extra_scalars: dict[str, float | str | int | bool],
    n: int,
    seed: int,
    return_samples: bool,
    warnings: list[CalcWarning],
    assumptions: tuple[str, ...],
) -> CalculationRecord:
    summ = _summary(x)
    values: dict[str, NDArray[np.float64] | float | int] = {
        f"{key}_{k}": v for k, v in summ.items()
    }
    units = {f"{key}_{k}": unit for k in summ}
    values["n_samples"] = n
    units["n_samples"] = "count"
    if return_samples:
        values[f"{key}_samples"] = x
        units[f"{key}_samples"] = unit
    return make_record(
        method=method,
        method_reference=REF_MC,
        maturity="M2",
        values=values,
        units=units,
        scalar_inputs={
            **{k: d.describe() for k, d in dists.items()},
            **extra_scalars,
            "n_samples": n,
            "seed": seed,
            "return_samples": return_samples,
        },
        array_inputs={},
        assumptions=assumptions,
        warnings=warnings,
    )


def mc_archie_sw(
    *,
    porosity: Distribution,
    rt_ohm_m: Distribution,
    rw_ohm_m: Distribution,
    a: Distribution,
    m: Distribution,
    n: Distribution,
    clip: bool,
    n_samples: int,
    seed: int,
    return_samples: bool,
) -> CalculationRecord:
    """Monte Carlo distribution of Archie Sw (uses the library's Archie equation).

    Parameters
    ----------
    porosity, rt_ohm_m, rw_ohm_m, a, m, n : Distribution
        Independent input distributions (porosity fraction in (0, 1]; resistivities in
        ohm·m; a, m, n > 0). Use :class:`Fixed` for known values.
    clip : bool
        Clip each Sw sample to [0, 1] before summarising. Samples with raw Sw > 1 are
        always counted in a warning.
    n_samples : int
        Number of samples (100 … 1e7).
    seed : int
        Seed of the PCG64 generator (>= 0). Mandatory for reproducibility.
    return_samples : bool
        Include the full sample array (``sw_samples``) in the record.

    Returns
    -------
    CalculationRecord
        ``sw_p90_low``, ``sw_p50``, ``sw_p10_high`` (PRMS exceedance convention),
        ``sw_mean``, ``sw_std``, ``sw_se_mean``, ``n_samples`` (+ ``sw_samples``).

    Raises
    ------
    InputValidationError
        Invalid settings or any sample outside the physical domain (e.g. porosity <= 0).

    Notes
    -----
    Maturity: M2. Clean formations only (as Archie). Assumptions: A-019, A-020.
    """
    _settings(n_samples, seed)
    clip = require_bool("clip", clip)
    dists = {
        "porosity": porosity,
        "rt_ohm_m": rt_ohm_m,
        "rw_ohm_m": rw_ohm_m,
        "a": a,
        "m": m,
        "n": n,
    }
    s = _sample_all(dists, n_samples, seed)
    phi = s["porosity"]
    if np.any((phi <= 0.0) | (phi > 1.0)):
        raise InputValidationError(
            "porosity: some samples fall outside (0, 1]; truncate "
            "the distribution (e.g. Normal(low=…, high=…))"
        )
    for k in ("rt_ohm_m", "rw_ohm_m", "a", "m", "n"):
        if np.any(s[k] <= 0.0):
            raise InputValidationError(
                f"{k}: some samples are <= 0; truncate the distribution or use LogNormal"
            )
    sw = _pp._archie_sw(phi, s["rt_ohm_m"], s["rw_ohm_m"], s["a"], s["m"], s["n"])
    warnings: list[CalcWarning] = []
    above = int(np.count_nonzero(sw > 1.0))
    if above:
        action = "clipped to 1" if clip else "kept unclipped"
        warnings.append(
            CalcWarning(
                "OUT_OF_RANGE_RAW", f"{above} of {n_samples} samples have raw Sw > 1 ({action})"
            )
        )
    if clip:
        sw = np.clip(sw, 0.0, 1.0)
    return _record(
        "uncertainty.mc_archie_sw",
        "sw",
        "fraction",
        sw,
        dists,
        {"clip": clip},
        n_samples,
        seed,
        return_samples,
        warnings,
        ("A-019", "A-020"),
    )


def mc_arps_eur(
    *,
    qi: Distribution,
    di: Distribution,
    b: Distribution,
    time_unit: _dca.TimeUnit,
    d_terminal: float | None,
    q_limit: float | None,
    t_horizon: float | None,
    n_samples: int,
    seed: int,
    return_samples: bool,
) -> CalculationRecord:
    """Monte Carlo distribution of Arps EUR (uses the library's Arps equations).

    Parameters
    ----------
    qi, di, b : Distribution
        Independent distributions of initial rate (> 0), nominal decline per
        ``time_unit`` (> 0) and b in [0, 2].
    time_unit, d_terminal, q_limit, t_horizon
        As in :func:`georeservoir.engineering.dca.arps_eur` (deterministic). If any b
        sample is >= 1, ``d_terminal`` is required (A-012).
    n_samples, seed, return_samples
        As in :func:`mc_archie_sw`.

    Returns
    -------
    CalculationRecord
        ``eur_p90_low``, ``eur_p50``, ``eur_p10_high`` (PRMS exceedance convention),
        ``eur_mean``, ``eur_std``, ``eur_se_mean``, ``n_samples`` (+ ``eur_samples``),
        in rate unit × ``time_unit``.

    Notes
    -----
    Maturity: M2. Assumptions: A-010, A-011, A-012, A-019, A-020.
    """
    _settings(n_samples, seed)
    dists = {"qi": qi, "di": di, "b": b}
    s = _sample_all(dists, n_samples, seed)
    tu = _dca._time_unit(time_unit)
    if np.any(s["qi"] <= 0.0) or np.any(s["di"] <= 0.0):
        raise InputValidationError("qi/di: some samples are <= 0; truncate the distribution")
    if np.any((s["b"] < 0.0) | (s["b"] > _dca.B_MAX)):
        raise InputValidationError(f"b: some samples fall outside [0, {_dca.B_MAX}]")
    if d_terminal is None and np.any(s["b"] >= 1.0):
        raise InputValidationError(
            "d_terminal: received None while some b samples are >= 1; "
            "EUR then requires a terminal decline (A-012)"
        )
    dt = None if d_terminal is None else check_positive_scalar("d_terminal", d_terminal)
    if q_limit is None and t_horizon is None:
        raise InputValidationError(
            "q_limit and t_horizon: received None for both; expected at least one cut-off"
        )
    ql = None if q_limit is None else check_positive_scalar("q_limit", q_limit)
    th = None if t_horizon is None else check_positive_scalar("t_horizon", t_horizon)
    if ql is not None and np.any(s["qi"] <= ql):
        raise InputValidationError("q_limit: some qi samples are <= q_limit; truncate qi")
    warnings: list[CalcWarning] = []
    n_b1 = int(np.count_nonzero(s["b"] > 1.0))
    if n_b1:
        warnings.append(
            CalcWarning(
                "B_GREATER_THAN_ONE",
                f"{n_b1} of {n_samples} b samples exceed 1 (transient "
                "flow; long extrapolations overestimate reserves)",
            )
        )
    eur = np.empty(n_samples)
    for i in range(n_samples):  # scalar closed forms; loop documented (spec §6.5)
        q0, d0, b0 = float(s["qi"][i]), float(s["di"][i]), float(s["b"][i])
        cands = [] if th is None else [th]
        if ql is not None:
            cands.append(_dca._time_to_rate(ql, q0, d0, b0, dt))
        t_end = np.array([min(cands)])
        eur[i] = float(_dca._modified(t_end, q0, d0, b0, dt)[1][0])
    return _record(
        "uncertainty.mc_arps_eur",
        "eur",
        f"rate unit x {tu}",
        eur,
        dists,
        {
            "time_unit": tu,
            "d_terminal": "none" if dt is None else dt,
            "q_limit": "none" if ql is None else ql,
            "t_horizon": "none" if th is None else th,
        },
        n_samples,
        seed,
        return_samples,
        warnings,
        ("A-010", "A-011", "A-012", "A-019", "A-020"),
    )
