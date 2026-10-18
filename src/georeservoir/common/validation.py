"""Input validation helpers.

All helpers return *new* float64 arrays (defensive copies) so that caller data is
never modified, and raise :class:`InputValidationError` with the parameter name,
the received value, the expected domain and the offending index.

NaN policy: NaN and ±inf are rejected everywhere in v0.1 (no silent propagation).

Maturity: M2
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from georeservoir.common.exceptions import InputValidationError

__all__ = [
    "as_1d_array",
    "check_in_closed_range",
    "check_positive_scalar",
    "check_same_length",
    "check_strictly_increasing",
    "require_bool",
    "require_finite_scalar",
]


def as_1d_array(name: str, value: ArrayLike, *, min_size: int = 1) -> NDArray[np.float64]:
    """Return ``value`` as a finite 1-D float64 copy.

    Scalars are promoted to shape ``(1,)``.

    Raises
    ------
    InputValidationError
        If ``value`` is not numeric, not 0-D/1-D, shorter than ``min_size`` or has
        non-finite elements.
    """
    try:
        arr = np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            f"{name}: received {value!r}; expected a real number or 1-D array of real numbers"
        ) from exc
    if arr.ndim == 0:
        arr = arr.reshape(1)
    if arr.ndim != 1:
        raise InputValidationError(
            f"{name}: received array with shape {arr.shape}; expected a 1-D array"
        )
    if arr.size < min_size:
        raise InputValidationError(
            f"{name}: received {arr.size} element(s); expected at least {min_size}"
        )
    bad = np.flatnonzero(~np.isfinite(arr))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"{name}[{i}]: received {arr[i]!r}; expected a finite value "
            f"({bad.size} non-finite element(s) in total)"
        )
    return arr


def require_finite_scalar(name: str, value: float) -> float:
    """Return ``value`` as a finite float or raise :class:`InputValidationError`."""
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{name}: received {value!r}; expected a real number") from exc
    if not np.isfinite(v):
        raise InputValidationError(f"{name}: received {v!r}; expected a finite value")
    return v


def check_positive_scalar(name: str, value: float) -> float:
    """Return ``value`` as a float if finite and strictly positive."""
    v = require_finite_scalar(name, value)
    if v <= 0.0:
        raise InputValidationError(f"{name}: received {v!r}; expected a value > 0")
    return v


def check_in_closed_range(name: str, arr: NDArray[np.float64], low: float, high: float) -> None:
    """Raise if any element of ``arr`` lies outside ``[low, high]``."""
    bad = np.flatnonzero((arr < low) | (arr > high))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"{name}[{i}]: received {arr[i]!r}; expected a value in [{low}, {high}] "
            f"({bad.size} element(s) out of range)"
        )


def check_strictly_increasing(name: str, arr: NDArray[np.float64]) -> None:
    """Raise if ``arr`` is not strictly increasing."""
    d = np.diff(arr)
    bad = np.flatnonzero(d <= 0.0)
    if bad.size:
        i = int(bad[0]) + 1
        raise InputValidationError(
            f"{name}[{i}]: received {arr[i]!r} after {arr[i - 1]!r}; "
            "expected strictly increasing values"
        )


def check_same_length(**arrays: NDArray[np.float64]) -> None:
    """Raise if the given arrays do not all have the same length."""
    sizes = {k: v.size for k, v in arrays.items()}
    if len(set(sizes.values())) > 1:
        raise InputValidationError(f"array lengths differ: {sizes}; expected equal lengths")


def require_bool(name: str, value: bool) -> bool:
    """Return ``value`` if it is a real ``bool`` (not merely truthy)."""
    if not isinstance(value, (bool, np.bool_)):
        raise InputValidationError(f"{name}: received {value!r}; expected True or False")
    return bool(value)
