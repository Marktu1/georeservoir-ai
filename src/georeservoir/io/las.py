"""LAS 1.2 / 2.0 reader with file provenance, unit/mnemonic normalisation and a
validation report.

Parsing of the LAS text is delegated to ``lasio`` (MIT licence; ADR-0004). This module adds
what an auditable workflow needs on top: the SHA-256 of the exact bytes read, every header
item preserved verbatim, NULL handling restricted to the declared NULL value, detection of
other suspicious sentinels (reported, never replaced), index checks (monotonic, duplicates,
irregular sampling, header STRT/STOP/STEP consistency), unit and mnemonic normalisation with
an explicit report, and parser warnings captured into the report.

LAS 3.0 is **M0** (not supported): it raises :class:`NotImplementedError`.

Maturity: M2
"""

from __future__ import annotations

import io
import logging
import re
import warnings as _warnings
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal

import numpy as np
from numpy.typing import NDArray

from georeservoir.common.exceptions import InputValidationError
from georeservoir.io.conventions import (
    CANONICAL_CURVES,
    canonical_mnemonic,
    conversion_factor,
    normalize_unit,
)
from georeservoir.io.provenance import (
    CheckStatus,
    FileProvenance,
    QualityCheck,
    ValidationReport,
    file_provenance,
)

__all__ = ["HeaderItem", "LasCurve", "WellLog", "read_las"]

#: Common sentinels that are *reported* (never replaced) when they differ from the NULL.
SUSPECT_SENTINELS: Final[tuple[float, ...]] = (
    -999.25,
    -999.0,
    -9999.0,
    -9999.25,
    999.25,
    9999.0,
    -99999.0,
)
#: Relative tolerance for comparing sample spacing with the header STEP (A-022).
STEP_RTOL: Final[float] = 1e-3
OnError = Literal["raise", "report"]
_DECIMAL_COMMA = re.compile(r"(?<![\w.,])-?\d+,\d+(?![\w.,])")


@dataclass(frozen=True, slots=True)
class HeaderItem:
    """One header line.

    ``value`` is the text exactly as written in the file (no number re-formatting);
    ``value_parsed`` is the parser's interpretation (e.g. ``1670.0`` for ``1670.000000``).
    """

    mnemonic: str
    unit: str
    value: str
    description: str
    value_parsed: str

    def to_dict(self) -> dict[str, str]:
        return {
            "mnemonic": self.mnemonic,
            "unit": self.unit,
            "value": self.value,
            "description": self.description,
            "value_parsed": self.value_parsed,
        }


@dataclass(frozen=True, slots=True)
class LasCurve:
    """A log curve: verbatim header fields + normalised unit/mnemonic + data (NaN = null)."""

    mnemonic: str
    unit_raw: str
    unit: str | None
    canonical: str | None
    api_code: str
    description: str
    values: NDArray[np.float64]
    n_null: int


@dataclass(frozen=True)
class WellLog:
    """Result of :func:`read_las`. Arrays are read-only; NaN marks declared-NULL samples."""

    provenance: FileProvenance
    las_version: str
    wrapped: bool
    null_value: float | None
    index_mnemonic: str
    index_unit: str | None
    index: NDArray[np.float64]
    curves: Mapping[str, LasCurve]
    version_section: tuple[HeaderItem, ...]
    well_section: tuple[HeaderItem, ...]
    parameter_section: tuple[HeaderItem, ...]
    other_section: str
    canonical_map: Mapping[str, str]
    report: ValidationReport
    _order: tuple[str, ...] = field(default=(), repr=False)

    @property
    def curve_names(self) -> tuple[str, ...]:
        return self._order

    def curve(self, name: str) -> LasCurve:
        """Curve by original mnemonic (as parsed, upper-case) or by canonical name."""
        key = name.upper()
        if key in self.curves:
            return self.curves[key]
        if key in self.canonical_map:
            return self.curves[self.canonical_map[key]]
        raise InputValidationError(
            f"curve: received {name!r}; available: {list(self._order)} "
            f"(canonical: {sorted(self.canonical_map)})"
        )

    def values_in(self, name: str, unit: str) -> NDArray[np.float64]:
        """Curve values converted to a canonical ``unit`` with an exact factor.

        Raises
        ------
        InputValidationError
            Unknown source unit or no exact conversion to ``unit`` (never guessed).
        """
        c = self.curve(name)
        if c.unit is None:
            raise InputValidationError(
                f"{c.mnemonic}: unit {c.unit_raw!r} is not recognised; cannot convert to "
                f"{unit!r} (declare the unit or convert explicitly)"
            )
        factor = conversion_factor(c.unit, unit)
        if factor is None:
            raise InputValidationError(
                f"{c.mnemonic}: no exact conversion from {c.unit!r} to {unit!r}"
            )
        out: NDArray[np.float64] = c.values * factor
        out.setflags(write=False)
        return out

    def index_in(self, unit: Literal["m", "ft"]) -> NDArray[np.float64]:
        """Index values converted to metres or feet (exact factor)."""
        if self.index_unit is None:
            raise InputValidationError("index unit is not recognised; cannot convert")
        factor = conversion_factor(self.index_unit, unit)
        if factor is None:
            raise InputValidationError(f"index: no conversion from {self.index_unit!r}")
        out: NDArray[np.float64] = self.index * factor
        out.setflags(write=False)
        return out

    def valid_mask(self, *names: str) -> NDArray[np.bool_]:
        """True where the index and all named curves are finite (not NULL)."""
        mask = np.isfinite(self.index)
        for n in names:
            mask &= np.isfinite(self.curve(n).values)
        return mask

    def summary(self) -> dict[str, Any]:
        return {
            "provenance": self.provenance.to_dict(),
            "las_version": self.las_version,
            "wrapped": self.wrapped,
            "null_value": self.null_value,
            "index": {
                "mnemonic": self.index_mnemonic,
                "unit": self.index_unit,
                "n": int(self.index.size),
            },
            "curves": [
                {
                    "mnemonic": c.mnemonic,
                    "unit_raw": c.unit_raw,
                    "unit": c.unit,
                    "canonical": c.canonical,
                    "n_null": c.n_null,
                }
                for c in (self.curves[n] for n in self._order)
            ],
            "report": self.report.to_dict(),
        }


# --------------------------------------------------------------------------- helpers
class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def _capture_lasio() -> Iterator[_Collector]:
    logger = logging.getLogger("lasio")
    handler = _Collector()
    old_propagate = logger.propagate
    logger.addHandler(handler)
    logger.propagate = False
    try:
        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            yield handler
        handler.messages.extend(str(w.message) for w in caught)
    finally:
        logger.removeHandler(handler)
        logger.propagate = old_propagate


def _raw_sections(text: str) -> dict[str, list[str]]:
    """Header lines per section letter (V, W, C, P), comments and blanks removed."""
    out: dict[str, list[str]] = {}
    cur = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("~"):
            cur = s[1:2].upper()
            if cur == "A":
                break
            out.setdefault(cur, [])
        elif cur in ("V", "W", "C", "P") and s and not s.startswith("#"):
            out[cur].append(line)
    return out


def _raw_value(line: str) -> str:
    """Text between the unit field and the last colon of a LAS header line, stripped."""
    if "." not in line:
        return ""
    after = line.split(".", 1)[1]
    body = after.rsplit(":", 1)[0] if ":" in after else after
    if body[:1].isspace() or body == "":
        return body.strip()
    parts = body.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _items(
    section: Any, raw_lines: list[str] | None, name: str, checks: list[QualityCheck]
) -> tuple[HeaderItem, ...]:
    parsed = list(section)
    raw = raw_lines or []
    use_raw = len(raw) == len(parsed) and all(
        ln.split(".", 1)[0].strip().upper() == str(i.mnemonic).split(":")[0].upper()
        for ln, i in zip(raw, parsed, strict=True)
    )
    if parsed and not use_raw:
        checks.append(
            QualityCheck(
                "HEADER_RAW_UNAVAILABLE",
                "warn",
                f"~{name}: could not align raw header lines with parsed items; 'value' holds "
                "the parser's text",
            )
        )
    out = []
    for k, i in enumerate(parsed):
        value_raw = _raw_value(raw[k]) if use_raw else str(i.value)
        out.append(HeaderItem(str(i.mnemonic), str(i.unit), value_raw, str(i.descr), str(i.value)))
    return tuple(out)


def _float_or_none(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        if enc == "utf-16" and "~" not in text:
            continue
        return text, enc
    return data.decode("latin-1"), "latin-1"


def _index_checks(
    idx: NDArray[np.float64], well: Mapping[str, HeaderItem], checks: list[QualityCheck]
) -> None:
    bad = np.flatnonzero(~np.isfinite(idx))
    if bad.size:
        checks.append(
            QualityCheck(
                "INDEX_NULL",
                "fail",
                f"{bad.size} index value(s) are NULL/non-finite",
                indices=tuple(int(i) for i in bad),
            )
        )
    finite = idx[np.isfinite(idx)]
    if finite.size < 2:
        checks.append(
            QualityCheck("INDEX_TOO_SHORT", "warn", f"{finite.size} valid index sample(s)")
        )
        return
    d = np.diff(finite)
    if np.all(d > 0):
        direction = "increasing"
    elif np.all(d < 0):
        direction = "decreasing"
        checks.append(
            QualityCheck(
                "INDEX_DECREASING", "info", "index decreases with sample number (kept as stored)"
            )
        )
    else:
        direction = "mixed"
        dup = np.flatnonzero(d == 0)
        rev = np.flatnonzero(np.sign(d) != np.sign(np.median(d)))
        if dup.size:
            checks.append(
                QualityCheck(
                    "INDEX_DUPLICATES",
                    "fail",
                    f"{dup.size} repeated index value(s)",
                    indices=tuple(int(i) + 1 for i in dup),
                )
            )
        if rev.size and not dup.size:
            checks.append(
                QualityCheck(
                    "INDEX_NOT_MONOTONIC",
                    "fail",
                    f"index reverses direction at {rev.size} point(s)",
                    indices=tuple(int(i) + 1 for i in rev),
                )
            )
    step_hdr = _float_or_none(well["STEP"].value_parsed) if "STEP" in well else None
    if direction != "mixed":
        med = float(np.median(d))
        dev = float(np.max(np.abs(d - med)) / abs(med))
        if step_hdr == 0.0 or dev > STEP_RTOL:
            sev: CheckStatus = "info" if step_hdr == 0.0 else "warn"
            checks.append(
                QualityCheck(
                    "IRREGULAR_SAMPLING",
                    sev,
                    f"sample spacing varies (max relative deviation "
                    f"{dev:.3g} from median {med:.6g}); header STEP = "
                    f"{step_hdr}",
                )
            )
        elif step_hdr is not None and abs(step_hdr - med) > STEP_RTOL * abs(med):
            checks.append(
                QualityCheck(
                    "HEADER_STEP_MISMATCH",
                    "warn",
                    f"header STEP {step_hdr} differs from data spacing {med:.6g}",
                )
            )
    for key, val in (("STRT", finite[0]), ("STOP", finite[-1])):
        h = _float_or_none(well[key].value_parsed) if key in well else None
        tol = STEP_RTOL * max(abs(float(np.median(d))), 1e-12)
        if h is None:
            checks.append(
                QualityCheck(
                    f"HEADER_{key}_MISSING", "warn", f"{key} missing or not numeric in ~W"
                )
            )
        elif abs(h - float(val)) > tol:
            checks.append(
                QualityCheck(
                    f"HEADER_{key}_MISMATCH",
                    "warn",
                    f"header {key} = {h} but data has {float(val)}",
                )
            )


# --------------------------------------------------------------------------- reader
def read_las(path: str | Path, *, on_error: OnError) -> WellLog:
    """Read a LAS 1.2 or 2.0 file with provenance and a validation report.

    Parameters
    ----------
    path : str or Path
        File to read. The exact bytes are hashed (SHA-256) before parsing.
    on_error : {"raise", "report"}
        ``"raise"``: raise :class:`InputValidationError` if any check has status
        ``fail`` (e.g. NULL or duplicate index values). ``"report"``: return the log and
        let the caller inspect ``WellLog.report``.

    Returns
    -------
    WellLog
        Verbatim header sections, curves (NaN where the value equals the declared NULL),
        normalised units/mnemonics, provenance and validation report.

    Raises
    ------
    InputValidationError
        File missing/unreadable, unparseable, or failed checks with ``on_error="raise"``.
    NotImplementedError
        LAS 3.0 (M0) or an unknown version.
    ImportError
        ``lasio`` is not installed (``pip install georeservoir[io]``).

    Notes
    -----
    Maturity: M2. Assumptions: A-021, A-022, A-023.
    """
    if on_error not in ("raise", "report"):
        raise InputValidationError(
            f"on_error: received {on_error!r}; expected 'raise' or 'report'"
        )
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise InputValidationError(f"path: cannot read {str(p)!r}: {exc}") from exc
    try:
        import lasio
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "read_las needs the optional dependency lasio: pip install 'georeservoir[io]'"
        ) from exc

    text, encoding = _decode(data)
    checks: list[QualityCheck] = []
    with _capture_lasio() as cap:
        try:
            las = lasio.read(
                io.StringIO(text),
                null_policy="strict",
                ignore_header_errors=False,
                mnemonic_case="upper",
            )
        except Exception as exc:  # lasio raises many exception types
            raise InputValidationError(
                f"{p.name}: LAS parsing failed ({type(exc).__name__}: {exc})"
            ) from exc

    vers_items = {i.mnemonic: i for i in las.version}
    version = str(vers_items["VERS"].value).strip() if "VERS" in vers_items else ""
    vnum = _float_or_none(version)
    if vnum is not None and vnum >= 3.0:
        raise NotImplementedError(
            f"{p.name}: LAS {version} is not supported (M0). LAS 3.0 support is planned; "
            "export the file as LAS 2.0 or see docs/roadmap.md"
        )
    if vnum not in (1.2, 2.0):
        raise NotImplementedError(
            f"{p.name}: LAS version {version!r} is not supported; expected 1.2 or 2.0"
        )
    if "VERS" not in vers_items:  # pragma: no cover - lasio requires VERS to read data
        checks.append(QualityCheck("VERSION_MISSING", "warn", "VERS missing in ~V"))
    wrapped = (
        str(vers_items["WRAP"].value).strip().upper() == "YES" if "WRAP" in vers_items else False
    )
    if wrapped:
        checks.append(QualityCheck("WRAPPED", "info", "wrapped file (WRAP = YES) unwrapped"))
    checks.append(QualityCheck("ENCODING", "info", f"decoded as {encoding}"))

    raw_sec = _raw_sections(text)
    well = _items(las.well, raw_sec.get("W"), "W", checks)
    well_map = {h.mnemonic: h for h in well}
    null_value = _float_or_none(well_map["NULL"].value_parsed) if "NULL" in well_map else None
    if null_value is None:
        checks.append(
            QualityCheck(
                "NULL_MISSING",
                "warn",
                "no NULL value declared in ~W: no samples were treated as missing",
            )
        )

    raw_curves = list(las.curves)
    if not raw_curves:
        raise InputValidationError(f"{p.name}: no curves defined in ~C")
    data_arr = np.asarray(las.data, dtype=np.float64)
    if data_arr.ndim != 2:
        data_arr = (
            data_arr.reshape(-1, len(raw_curves))
            if data_arr.size
            else np.empty((0, len(raw_curves)))
        )
    if data_arr.shape[0] == 0:
        checks.append(QualityCheck("NO_DATA", "warn", "~A section has no data rows"))

    idx_curve = raw_curves[0]
    index = np.array(data_arr[:, 0], dtype=np.float64) if data_arr.size else np.empty(0)
    index_unit = normalize_unit(str(idx_curve.unit))
    if index_unit not in ("m", "ft"):
        checks.append(
            QualityCheck(
                "INDEX_UNIT_UNKNOWN",
                "warn",
                f"index unit {idx_curve.unit!r} is not m or ft",
                curve=str(idx_curve.mnemonic),
            )
        )
        index_unit = None if index_unit in (None, "") else index_unit
    _index_checks(index, well_map, checks)
    if null_value is not None and index.size:
        hits = np.flatnonzero(index == null_value)
        if hits.size:
            checks.append(
                QualityCheck(
                    "INDEX_EQUALS_NULL",
                    "warn",
                    f"{hits.size} index value(s) equal the declared NULL {null_value}; kept as "
                    "depths (the index is never nulled) — check the NULL choice",
                    curve=str(idx_curve.mnemonic),
                    indices=tuple(int(i) for i in hits),
                )
            )
    a_pos = text.upper().find("\n~A")
    if a_pos >= 0:
        commas = _DECIMAL_COMMA.findall(text[a_pos:])
        if commas:
            checks.append(
                QualityCheck(
                    "DECIMAL_COMMA",
                    "warn",
                    f"{len(commas)} token(s) like {commas[0]!r} in ~A: the parser reads the comma "
                    "as a decimal mark; if it is a thousands separator the values are wrong",
                )
            )

    curves: dict[str, LasCurve] = {}
    order: list[str] = []
    canon_hits: dict[str, list[str]] = {}
    for j, c in enumerate(raw_curves):
        name = str(c.mnemonic)
        vals = np.array(data_arr[:, j], dtype=np.float64) if data_arr.size else np.empty(0)
        n_null = int(np.count_nonzero(~np.isfinite(vals)))
        if j > 0 and n_null:
            checks.append(
                QualityCheck(
                    "NULL_SAMPLES", "info", f"{n_null} sample(s) equal to NULL → NaN", curve=name
                )
            )
        if null_value is not None and vals.size:
            for s in SUSPECT_SENTINELS:
                if s == null_value:
                    continue
                hits = np.flatnonzero(vals == s)
                if hits.size:
                    checks.append(
                        QualityCheck(
                            "SUSPECT_SENTINEL",
                            "warn",
                            f"{hits.size} sample(s) equal to {s}, a common null sentinel that "
                            f"differs from the declared NULL {null_value}; NOT replaced",
                            curve=name,
                            indices=tuple(int(i) for i in hits),
                        )
                    )
        unit = normalize_unit(str(c.unit))
        if unit is None:
            checks.append(
                QualityCheck(
                    "UNIT_UNKNOWN",
                    "warn",
                    f"unit {c.unit!r} not recognised; kept verbatim",
                    curve=name,
                )
            )
        canon = canonical_mnemonic(name) if j > 0 else "DEPT"
        if canon is not None:
            canon_hits.setdefault(canon, []).append(name)
        vals.setflags(write=False)
        curves[name] = LasCurve(
            name, str(c.unit), unit, canon, str(c.value), str(c.descr), vals, n_null
        )
        order.append(name)
        if ":" in name:
            checks.append(
                QualityCheck(
                    "DUPLICATE_MNEMONIC",
                    "warn",
                    f"mnemonic repeated in ~C; parser renamed it {name!r}",
                    curve=name,
                )
            )

    canonical_map: dict[str, str] = {}
    for canon, names in canon_hits.items():
        if len(names) == 1:
            canonical_map[canon] = names[0]
            if names[0] != canon:
                checks.append(
                    QualityCheck(
                        "MNEMONIC_MAPPED",
                        "info",
                        f"{names[0]} → {canon} ({CANONICAL_CURVES[canon][0]})",
                        curve=names[0],
                    )
                )
        else:
            checks.append(
                QualityCheck(
                    "MNEMONIC_AMBIGUOUS",
                    "warn",
                    f"{names} all map to {canon}; no canonical alias assigned (choose explicitly)",
                    curve=canon,
                )
            )

    for msg in dict.fromkeys(cap.messages):  # de-duplicated, ordered
        checks.append(QualityCheck("PARSER_WARNING", "warn", msg))

    index.setflags(write=False)
    prov = file_provenance(
        p,
        data,
        file_format="LAS",
        format_version=version,
        parser="lasio",
        parser_version=str(lasio.__version__),
    )
    version_section = _items(las.version, raw_sec.get("V"), "V", checks)
    parameter_section = _items(las.params, raw_sec.get("P"), "P", checks)
    report = ValidationReport(tuple(checks))
    if on_error == "raise" and report.status == "fail":
        fails = [c for c in checks if c.status == "fail"]
        raise InputValidationError(
            f"{p.name}: validation failed: " + "; ".join(f"{c.code}: {c.message}" for c in fails)
        )
    return WellLog(
        provenance=prov,
        las_version=version,
        wrapped=wrapped,
        null_value=null_value,
        index_mnemonic=str(idx_curve.mnemonic),
        index_unit=index_unit,
        index=index,
        curves=MappingProxyType(curves),
        version_section=version_section,
        well_section=well,
        parameter_section=parameter_section,
        other_section=str(las.other),
        canonical_map=MappingProxyType(canonical_map),
        report=report,
        _order=tuple(order),
    )
