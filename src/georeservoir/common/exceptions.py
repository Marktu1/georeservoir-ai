"""Exception hierarchy for GeoReservoir.

Every error message states: the parameter, the value received, the expected
domain and, for arrays, the index of the offending element.
"""

from __future__ import annotations

__all__ = [
    "GeoReservoirError",
    "IdentifiabilityError",
    "InputValidationError",
    "NumericalError",
    "PhysicalConsistencyError",
]


class GeoReservoirError(Exception):
    """Base class for every error raised by GeoReservoir."""


class InputValidationError(GeoReservoirError, ValueError):
    """An input is outside its declared domain (shape, range, finiteness, type)."""


class PhysicalConsistencyError(GeoReservoirError, ValueError):
    """Inputs are individually valid but describe a physically impossible configuration."""


class NumericalError(GeoReservoirError, ArithmeticError):
    """A quantity is mathematically undefined or an algorithm did not converge."""


class IdentifiabilityError(GeoReservoirError):
    """A fit is not identifiable (too few points, rank-deficient or ill-conditioned)."""
