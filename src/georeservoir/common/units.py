"""Explicit unit conversions to and from the canonical internal SI system.

Internal canonical units: metre (m), pascal (Pa), second (s), cubic metre (m³),
kilogram per cubic metre (kg/m³), radian (rad).

All factors below are exact by definition (international foot, international
pound, standard gravity) unless stated otherwise.

Maturity: M2
"""

from __future__ import annotations

from typing import Final, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

from georeservoir.common.exceptions import InputValidationError

__all__ = [
    "FT_TO_M",
    "G_CC_TO_KG_M3",
    "PSI_TO_PA",
    "US_PER_FT_TO_S_PER_M",
    "LengthUnit",
    "PressureUnit",
    "length_from_si",
    "length_to_si",
    "pressure_from_si",
    "pressure_to_si",
]

LengthUnit = Literal["m", "ft"]
PressureUnit = Literal["Pa", "kPa", "MPa", "psi", "bar"]

#: International foot, exact (1959 international yard and pound agreement).
FT_TO_M: Final[float] = 0.3048
#: 1 psi = 1 lbf/in² = 0.45359237 kg · 9.80665 m/s² / (0.0254 m)², exact.
PSI_TO_PA: Final[float] = 0.45359237 * 9.80665 / (0.0254**2)
#: 1 µs/ft expressed in s/m.
US_PER_FT_TO_S_PER_M: Final[float] = 1e-6 / FT_TO_M
#: 1 g/cm³ in kg/m³, exact.
G_CC_TO_KG_M3: Final[float] = 1000.0

_LENGTH: Final[dict[str, float]] = {"m": 1.0, "ft": FT_TO_M}
_PRESSURE: Final[dict[str, float]] = {
    "Pa": 1.0,
    "kPa": 1e3,
    "MPa": 1e6,
    "bar": 1e5,
    "psi": PSI_TO_PA,
}


def _factor(table: dict[str, float], unit: str, kind: str) -> float:
    try:
        return table[unit]
    except (KeyError, TypeError):
        raise InputValidationError(
            f"{kind} unit: received {unit!r}; expected one of {sorted(table)}"
        ) from None


def length_to_si(value: ArrayLike, unit: LengthUnit) -> NDArray[np.float64]:
    """Convert a length from ``unit`` to metres.

    Parameters
    ----------
    value : array_like
        Length(s) expressed in ``unit``.
    unit : {"m", "ft"}
        Unit of ``value``.

    Returns
    -------
    numpy.ndarray of float64
        Length(s) in metres (a new array; input is not modified).

    Raises
    ------
    InputValidationError
        If ``unit`` is not supported.
    """
    return np.asarray(value, dtype=np.float64) * _factor(_LENGTH, unit, "length")


def length_from_si(value_m: ArrayLike, unit: LengthUnit) -> NDArray[np.float64]:
    """Convert a length in metres to ``unit``. Inverse of :func:`length_to_si`."""
    return np.asarray(value_m, dtype=np.float64) / _factor(_LENGTH, unit, "length")


def pressure_to_si(value: ArrayLike, unit: PressureUnit) -> NDArray[np.float64]:
    """Convert a pressure from ``unit`` to pascals.

    Parameters
    ----------
    value : array_like
        Pressure(s) expressed in ``unit``.
    unit : {"Pa", "kPa", "MPa", "psi", "bar"}
        Unit of ``value``. Gauge/absolute convention is the caller's responsibility.
    """
    return np.asarray(value, dtype=np.float64) * _factor(_PRESSURE, unit, "pressure")


def pressure_from_si(value_pa: ArrayLike, unit: PressureUnit) -> NDArray[np.float64]:
    """Convert a pressure in pascals to ``unit``. Inverse of :func:`pressure_to_si`."""
    return np.asarray(value_pa, dtype=np.float64) / _factor(_PRESSURE, unit, "pressure")
