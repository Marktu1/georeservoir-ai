"""GeoReservoir AI — auditable subsurface engineering scientific core.

Every public calculation returns a :class:`~georeservoir.common.record.CalculationRecord`
that carries values, units, method, bibliographic reference, input hash, library
version, maturity level, assumptions and typed warnings.

This is a decision-support library. It does not replace qualified professionals,
input-data validation, or approval of workflows by technically responsible people.
"""

from georeservoir._version import __version__

__all__ = ["__version__"]
