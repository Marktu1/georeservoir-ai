"""The ``CalculationRecord`` result contract.

Every public calculation returns an immutable :class:`CalculationRecord`. Its
``inputs_hash`` is the SHA-256 of a canonical serialisation of the method id,
library version and inputs (arrays enter by shape + SHA-256 of their little-endian
float64 bytes). No timestamp is ever hashed, so the same calculation always yields
the same record.

Maturity: M2
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from georeservoir._version import __version__
from georeservoir.common.exceptions import InputValidationError, NumericalError

__all__ = [
    "CalcWarning",
    "CalculationRecord",
    "Maturity",
    "array_digest",
    "make_record",
]

Maturity = Literal["M0", "M1", "M2", "M3"]
ScalarInput = float | int | str | bool
Value = NDArray[np.float64] | float | int


@dataclass(frozen=True, slots=True)
class CalcWarning:
    """A typed warning attached to a result.

    Attributes
    ----------
    code : str
        Stable machine-readable code, e.g. ``"OUT_OF_RANGE_RAW"``.
    message : str
        Human-readable description.
    indices : tuple of int
        Indices of the affected elements (empty when not element-specific).
    """

    code: str
    message: str
    indices: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "indices": list(self.indices)}


def array_digest(arr: NDArray[np.float64]) -> dict[str, Any]:
    """Return ``{"shape": [...], "sha256": "..."}`` for a float64 array."""
    data = np.ascontiguousarray(arr, dtype="<f8").tobytes()
    return {"shape": list(arr.shape), "sha256": hashlib.sha256(data).hexdigest()}


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _jsonable(value: Value) -> Any:
    if isinstance(value, np.ndarray):
        return [float(x) for x in value.tolist()]
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    raise TypeError(f"unsupported value type {type(value)!r}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class CalculationRecord:
    """Immutable, serialisable, auditable result of a calculation.

    Arrays in ``values`` are read-only. Mappings are read-only proxies.
    """

    values: Mapping[str, Value]
    units: Mapping[str, str]
    method: str
    method_reference: str
    inputs: Mapping[str, Any]
    inputs_hash: str
    library_version: str
    maturity: Maturity
    assumptions: tuple[str, ...] = ()
    warnings: tuple[CalcWarning, ...] = field(default_factory=tuple)

    def __getitem__(self, key: str) -> Value:
        return self.values[key]

    def to_dict(self) -> dict[str, Any]:
        """Deterministic plain-Python representation (sorted keys when serialised)."""
        return {
            "values": {k: _jsonable(v) for k, v in sorted(self.values.items())},
            "units": dict(sorted(self.units.items())),
            "method": self.method,
            "method_reference": self.method_reference,
            "inputs": dict(sorted(self.inputs.items())),
            "inputs_hash": self.inputs_hash,
            "library_version": self.library_version,
            "maturity": self.maturity,
            "assumptions": list(self.assumptions),
            "warnings": [w.to_dict() for w in self.warnings],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Deterministic JSON (sorted keys; floats rendered with ``repr`` precision)."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent, allow_nan=False)


def make_record(
    *,
    method: str,
    method_reference: str,
    maturity: Maturity,
    values: Mapping[str, Value],
    units: Mapping[str, str],
    scalar_inputs: Mapping[str, ScalarInput],
    array_inputs: Mapping[str, NDArray[np.float64]],
    assumptions: Sequence[str] = (),
    warnings: Sequence[CalcWarning] = (),
) -> CalculationRecord:
    """Build a :class:`CalculationRecord`, freezing arrays and hashing the inputs.

    Raises
    ------
    InputValidationError
        If ``values`` and ``units`` keys differ, or a key appears in both input maps.
    NumericalError
        If any output value is NaN or ±inf (overflow, division by ~0): outputs are
        never returned non-finite.
    """
    if set(values) != set(units):
        raise InputValidationError(
            f"values/units keys differ: {sorted(set(values) ^ set(units))}; expected same keys"
        )
    clash = set(scalar_inputs) & set(array_inputs)
    if clash:
        raise InputValidationError(f"input names used twice: {sorted(clash)}")

    inputs: dict[str, Any] = dict(scalar_inputs)
    for name, arr in array_inputs.items():
        inputs[name] = array_digest(arr)

    payload = {"method": method, "library_version": __version__, "inputs": inputs}
    inputs_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    frozen: dict[str, Value] = {}
    for k, v in values.items():
        bad = np.flatnonzero(~np.isfinite(np.atleast_1d(np.asarray(v, dtype=np.float64))))
        if bad.size:
            i = int(bad[0])
            raise NumericalError(
                f"{method}: output {k!r}[{i}] is not finite; inputs are outside the range "
                f"where the method is numerically defined ({bad.size} element(s))"
            )
        if isinstance(v, np.ndarray):
            c = np.array(v, dtype=np.float64, copy=True)
            c.setflags(write=False)
            frozen[k] = c
        else:
            frozen[k] = v

    return CalculationRecord(
        values=MappingProxyType(frozen),
        units=MappingProxyType(dict(units)),
        method=method,
        method_reference=method_reference,
        inputs=MappingProxyType(inputs),
        inputs_hash=inputs_hash,
        library_version=__version__,
        maturity=maturity,
        assumptions=tuple(assumptions),
        warnings=tuple(warnings),
    )
