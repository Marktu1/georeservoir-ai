"""Mnemonic and unit normalisation for well-log curves.

Normalisation **never renames or converts silently**: the original mnemonic and unit
string are always kept, and every mapping is reported. Only exact, well-established
aliases are mapped (A-021). Unknown units are kept as given and flagged.

Maturity: M2
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "CANONICAL_CURVES",
    "UNIT_ALIASES",
    "UNIT_FACTORS",
    "canonical_mnemonic",
    "conversion_factor",
    "normalize_unit",
]

#: canonical name → (description, aliases). Matching is case-insensitive and exact.
CANONICAL_CURVES: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "DEPT": ("measured depth index", ("DEPT", "DEPTH", "MD")),
    "GR": ("total gamma ray", ("GR", "GAMMA")),
    "RHOB": ("bulk density", ("RHOB", "RHOZ", "DEN", "ZDEN")),
    "NPHI": ("neutron porosity", ("NPHI", "TNPH", "NPOR")),
    "DT": ("compressional slowness", ("DT", "DTC", "DTCO", "AC")),
    "RDEEP": (
        "deep resistivity (a reading, not true formation resistivity Rt)",
        ("ILD", "LLD", "RD", "RDEP", "AT90"),
    ),
    "SP": ("spontaneous potential", ("SP",)),
    "CALI": ("caliper", ("CALI", "CAL", "HCAL")),
    "PEF": ("photoelectric factor", ("PEF", "PEFZ", "PE")),
}
_ALIAS_TO_CANON: Final[dict[str, str]] = {
    alias: canon for canon, (_, aliases) in CANONICAL_CURVES.items() for alias in aliases
}

#: raw unit string (upper-case, spaces removed) → canonical unit
UNIT_ALIASES: Final[dict[str, str]] = {
    "M": "m",
    "METER": "m",
    "METERS": "m",
    "METRES": "m",
    "F": "ft",
    "FT": "ft",
    "FEET": "ft",
    "FOOT": "ft",
    "G/C3": "g/cc",
    "G/CC": "g/cc",
    "GM/CC": "g/cc",
    "G/CM3": "g/cc",
    "GR/CC": "g/cc",
    "K/M3": "kg/m3",
    "KG/M3": "kg/m3",
    "US/F": "us/ft",
    "US/FT": "us/ft",
    "USEC/FT": "us/ft",
    "US/FOOT": "us/ft",
    "US/M": "us/m",
    "USEC/M": "us/m",
    "OHMM": "ohm.m",
    "OHM.M": "ohm.m",
    "OHM-M": "ohm.m",
    "OHM_M": "ohm.m",
    "GAPI": "API",
    "API": "API",
    "GAPIU": "API",
    "V/V": "v/v",
    "FRAC": "v/v",
    "DEC": "v/v",
    "CFCF": "v/v",
    "M3/M3": "v/v",
    "PU": "percent",
    "%": "percent",
    "PERCENT": "percent",
    "MV": "mV",
    "IN": "in",
    "INCH": "in",
    "MM": "mm",
    "B/E": "b/e",
    "DEGC": "degC",
    "DEGF": "degF",
}

#: (from, to) → multiplicative factor; exact by definition.
UNIT_FACTORS: Final[dict[tuple[str, str], float]] = {
    ("m", "m"): 1.0,
    ("ft", "ft"): 1.0,
    ("ft", "m"): 0.3048,
    ("m", "ft"): 1.0 / 0.3048,
    ("g/cc", "g/cc"): 1.0,
    ("kg/m3", "g/cc"): 1e-3,
    ("g/cc", "kg/m3"): 1e3,
    ("kg/m3", "kg/m3"): 1.0,
    ("us/ft", "us/ft"): 1.0,
    ("us/m", "us/ft"): 0.3048,
    ("us/ft", "us/m"): 1.0 / 0.3048,
    ("us/m", "us/m"): 1.0,
    ("ohm.m", "ohm.m"): 1.0,
    ("API", "API"): 1.0,
    ("v/v", "v/v"): 1.0,
    ("percent", "v/v"): 0.01,
    ("v/v", "percent"): 100.0,
    ("percent", "percent"): 1.0,
}


def normalize_unit(raw: str) -> str | None:
    """Canonical unit for a raw LAS unit string, or ``None`` if unknown (not guessed)."""
    key = raw.strip().upper().replace(" ", "")
    if key == "":
        return ""
    return UNIT_ALIASES.get(key)


def canonical_mnemonic(raw: str) -> str | None:
    """Canonical curve name for a raw mnemonic, or ``None`` when not a known alias.

    Lasio suffixes duplicates as ``NAME:1``, ``NAME:2``; the suffix is ignored here and
    ambiguity is resolved (refused) by the reader.
    """
    base = raw.strip().upper().split(":")[0]
    return _ALIAS_TO_CANON.get(base)


def conversion_factor(from_unit: str, to_unit: str) -> float | None:
    """Exact factor to convert canonical ``from_unit`` to ``to_unit``, or ``None``."""
    return UNIT_FACTORS.get((from_unit, to_unit))
