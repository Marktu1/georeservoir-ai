"""Directional-survey reader (delimited text: CSV, TSV or whitespace) with provenance.

Pure Python (``csv`` module); no third-party parser. Column names, length unit and
azimuth reference are always declared by the caller — nothing is inferred from the file.
Comment lines start with ``#``. Every numeric parse error reports the line number.

Maturity: M2
"""

from __future__ import annotations

import csv
import io
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import numpy as np
from numpy.typing import NDArray

from georeservoir.common.exceptions import InputValidationError
from georeservoir.common.record import CalculationRecord
from georeservoir.common.units import LengthUnit
from georeservoir.engineering.well_path import AzimuthReference, minimum_curvature
from georeservoir.io.provenance import (
    FileProvenance,
    QualityCheck,
    ValidationReport,
    file_provenance,
)

__all__ = ["Survey", "read_survey"]

Delimiter = Literal[",", ";", "\t", "whitespace"]
_MISSING: Final[frozenset[str]] = frozenset({"", "NA", "NAN", "NULL", "N/A"})
#: Numeric values treated as null sentinels and refused (never used as data).
_SENTINELS: Final[frozenset[float]] = frozenset(
    {-999.0, -999.25, -9999.0, -9999.25, 999.25, 9999.0, -99999.0}
)


@dataclass(frozen=True)
class Survey:
    """Survey stations read from a file (arrays read-only)."""

    provenance: FileProvenance
    md: NDArray[np.float64]
    inclination_deg: NDArray[np.float64]
    azimuth_deg: NDArray[np.float64]
    length_unit: LengthUnit
    azimuth_reference: AzimuthReference
    source_lines: tuple[int, ...]
    report: ValidationReport

    def trajectory(
        self, *, start_east: float, start_north: float, start_tvd: float
    ) -> CalculationRecord:
        """Minimum-curvature trajectory of this survey (see ``well_path.minimum_curvature``)."""
        return minimum_curvature(
            self.md,
            self.inclination_deg,
            self.azimuth_deg,
            length_unit=self.length_unit,
            azimuth_reference=self.azimuth_reference,
            start_east=start_east,
            start_north=start_north,
            start_tvd=start_tvd,
        )


def _rows(text: str, delimiter: Delimiter) -> list[tuple[int, list[str]]]:
    """(physical line number, fields) for every non-blank, non-comment record."""
    out: list[tuple[int, list[str]]] = []
    if delimiter == "whitespace":
        for n, line in enumerate(text.splitlines(), start=1):
            s = line.strip()
            if s and not s.startswith("#"):
                out.append((n, s.split()))
        return out
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    start = 1
    for row in reader:
        # reader.line_num is the physical line where this record ended
        if row and any(c.strip() for c in row) and not row[0].strip().startswith("#"):
            out.append((start, [c.strip() for c in row]))
        start = reader.line_num + 1
    return out


def read_survey(
    path: str | Path,
    *,
    md_column: str,
    inclination_column: str,
    azimuth_column: str,
    length_unit: LengthUnit,
    azimuth_reference: AzimuthReference,
    delimiter: Delimiter,
) -> Survey:
    """Read a directional survey from a delimited text file with a header row.

    Parameters
    ----------
    path : str or Path
        File with one header row naming the columns, then one station per row.
    md_column, inclination_column, azimuth_column : str
        Header names (case-insensitive) of MD, inclination (degrees) and azimuth (degrees).
    length_unit : {"m", "ft"}
        Declared unit of MD (not inferred from the file).
    azimuth_reference : {"true", "magnetic", "grid"}
        Declared azimuth reference (not inferred; no correction applied).
    delimiter : {",", ";", "\\t", "whitespace"}
        Field separator.

    Returns
    -------
    Survey
        Stations, provenance (SHA-256 of the exact bytes) and validation report.

    Raises
    ------
    InputValidationError
        Unreadable file, missing columns, missing/non-numeric values (with line number),
        MD not strictly increasing, inclination outside [0, 180], fewer than 2 stations.

    Notes
    -----
    Maturity: M2. Assumptions: A-002, A-023.
    """
    if length_unit not in ("m", "ft"):
        raise InputValidationError(f"length_unit: received {length_unit!r}; expected 'm'/'ft'")
    if azimuth_reference not in ("true", "magnetic", "grid"):
        raise InputValidationError(
            f"azimuth_reference: received {azimuth_reference!r}; expected 'true', "
            "'magnetic' or 'grid'"
        )
    if delimiter not in (",", ";", "\t", "whitespace"):
        raise InputValidationError(f"delimiter: received {delimiter!r}")
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise InputValidationError(f"path: cannot read {str(p)!r}: {exc}") from exc
    enc_note = ""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text, enc_note = data.decode("cp1252"), "cp1252"
        except UnicodeDecodeError:
            text, enc_note = data.decode("latin-1"), "latin-1"
    rows = _rows(text, delimiter)
    if not rows:
        raise InputValidationError(f"{p.name}: no header row found")
    header_line, header = rows[0]
    names = [h.strip().upper() for h in header]
    cols: list[int] = []
    for label, wanted in (
        ("md_column", md_column),
        ("inclination_column", inclination_column),
        ("azimuth_column", azimuth_column),
    ):
        key = wanted.strip().upper()
        if names.count(key) != 1:
            raise InputValidationError(
                f"{label}: {wanted!r} found {names.count(key)} time(s) in header line "
                f"{header_line} {header}; expected exactly once"
            )
        cols.append(names.index(key))
    values: list[list[float]] = [[], [], []]
    lines: list[int] = []
    extra_rows: list[int] = []
    for line_no, row in rows[1:]:
        if len(row) > len(header):
            extra_rows.append(line_no)
        if len(row) <= max(cols):
            raise InputValidationError(
                f"{p.name}: line {line_no} has {len(row)} field(s); expected at least "
                f"{max(cols) + 1}"
            )
        for k, c in enumerate(cols):
            tok = row[c]
            if tok.upper() in _MISSING:
                raise InputValidationError(
                    f"{p.name}: line {line_no}, column {header[c]!r}: missing value {tok!r}; "
                    "surveys must be complete (remove or fix the station)"
                )
            try:
                v = float(tok)
            except ValueError:
                raise InputValidationError(
                    f"{p.name}: line {line_no}, column {header[c]!r}: {tok!r} is not a number"
                ) from None
            if not np.isfinite(v):
                raise InputValidationError(
                    f"{p.name}: line {line_no}, column {header[c]!r}: non-finite {tok!r}"
                )
            if v in _SENTINELS:
                raise InputValidationError(
                    f"{p.name}: line {line_no}, column {header[c]!r}: {tok!r} is a common "
                    "null sentinel, not a survey value; remove or fix the station"
                )
            values[k].append(v)
        lines.append(line_no)
    md, inc, azi = (np.array(v, dtype=np.float64) for v in values)
    if md.size < 2:
        raise InputValidationError(f"{p.name}: {md.size} station(s); expected at least 2")
    bad = np.flatnonzero(np.diff(md) <= 0.0)
    if bad.size:
        i = int(bad[0]) + 1
        raise InputValidationError(
            f"{p.name}: line {lines[i]}: MD {float(md[i])!r} after {float(md[i - 1])!r}; "
            "expected strictly increasing MD (duplicate stations must be removed)"
        )
    bad = np.flatnonzero((inc < 0.0) | (inc > 180.0))
    if bad.size:
        i = int(bad[0])
        raise InputValidationError(
            f"{p.name}: line {lines[i]}: inclination {float(inc[i])!r} outside [0, 180]"
        )
    checks: list[QualityCheck] = [
        QualityCheck(
            "DECLARED_UNITS",
            "info",
            f"MD in {length_unit}, azimuth reference {azimuth_reference} (declared by "
            "the caller, not read from the file)",
        )
    ]
    out_rng = np.flatnonzero((azi < 0.0) | (azi >= 360.0))
    if out_rng.size:
        checks.append(
            QualityCheck(
                "AZIMUTH_NORMALISED",
                "info",
                f"{out_rng.size} azimuth(s) outside [0, 360) will be "
                "normalised by the trajectory calculation",
                indices=tuple(int(i) for i in out_rng),
            )
        )
    if enc_note:
        checks.append(
            QualityCheck("ENCODING", "warn", f"decoded as {enc_note} (assumed: not valid UTF-8)")
        )
    if extra_rows:
        checks.append(
            QualityCheck(
                "EXTRA_FIELDS",
                "warn",
                f"{len(extra_rows)} row(s) have more fields than the header "
                f"(first at line {extra_rows[0]}); extra fields ignored",
            )
        )
    neg = np.flatnonzero(md < 0.0)
    if neg.size:
        checks.append(
            QualityCheck(
                "NEGATIVE_MD",
                "warn",
                f"{neg.size} station(s) with MD < 0 (above the depth datum?)",
                indices=tuple(int(i) for i in neg),
            )
        )
    if md[0] != 0.0:
        checks.append(
            QualityCheck(
                "FIRST_STATION_NOT_AT_ZERO",
                "info",
                f"first station MD = {md[0]}; give the tie-in coordinates "
                "as the trajectory start point",
            )
        )
    gaps = np.diff(md)
    big = np.flatnonzero(gaps > 10.0 * float(np.median(gaps)))
    if big.size:
        checks.append(
            QualityCheck(
                "LARGE_STATION_GAP",
                "warn",
                f"{big.size} interval(s) more than 10x the median spacing",
                indices=tuple(int(i) + 1 for i in big),
            )
        )
    for a in (md, inc, azi):
        a.setflags(write=False)
    prov = file_provenance(
        p,
        data,
        file_format="survey-delimited",
        format_version="n/a",
        parser="georeservoir.io.survey (csv)",
        parser_version=f"python {platform.python_version()}",
    )
    return Survey(
        prov,
        md,
        inc,
        azi,
        length_unit,
        azimuth_reference,
        tuple(lines),
        ValidationReport(tuple(checks)),
    )
