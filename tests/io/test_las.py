"""LAS reader tests, including the Phase 2 gate: public files read without metadata loss.

The gate compares the reader with an **independent** reference written here: the file
encoding comes from a fixed table (not detected), header lines are split with a regular
expression following the LAS 2.0 line grammar ``MNEM.UNIT  DATA : DESCRIPTION``, and the
~A section is tokenised with ``str.split``. Neither lasio nor georeservoir is used by the
reference. What the gate checks is listed in docs/validation/io.md.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest

from georeservoir.common.exceptions import InputValidationError
from georeservoir.io.las import read_las

DATA = Path(__file__).parents[1] / "data" / "las"
PROB = DATA / "problem"
# Public LAS 1.2/2.0 files (lasio test suite, MIT) and their known encodings.
GATE_FILES = {
    "sample.las": "ascii",
    "sample_2.0.las": "ascii",
    "sample_2.0_wrapped.las": "ascii",
    "sample_2.0_minimal.las": "ascii",
    "sample_curve_api.las": "ascii",
    "missing_null.las": "ascii",
    "encodings_cp1252.las": "cp1252",
    "encodings_utf16le.las": "utf-16",
}
LINE = re.compile(r"^\s*(?P<mnem>[^.]*?)\s*\.(?P<unit>[^\s]*)(?P<data>.*):(?P<desc>[^:]*)$")


def _sections(text: str) -> tuple[dict[str, list[str]], str, list[str]]:
    sec: dict[str, list[str]] = {}
    other: list[str] = []
    data: list[str] = []
    cur = ""
    for line in text.splitlines():
        if line.lstrip().startswith("~"):
            cur = line.lstrip()[1].upper()
            sec.setdefault(cur, [])
            continue
        if cur == "O":
            other.append(line)
        elif cur == "A":
            if line.strip():
                data.append(line)
        elif cur and line.strip() and not line.lstrip().startswith("#"):
            sec[cur].append(line)
    return sec, "\n".join(other), data


def _fields(line: str) -> tuple[str, str, str, str]:
    m = LINE.match(line)
    assert m is not None, line
    return m["mnem"], m["unit"], m["data"].strip(), m["desc"].strip()


@pytest.mark.parametrize("name", sorted(GATE_FILES))
def test_gate_no_metadata_or_data_loss(name: str) -> None:
    path = DATA / name
    raw = path.read_bytes()
    log = read_las(path, on_error="report")
    sec, other, data_lines = _sections(raw.decode(GATE_FILES[name]).lstrip("﻿"))

    # provenance: hash of the exact bytes
    assert log.provenance.sha256 == hashlib.sha256(raw).hexdigest()
    assert log.provenance.size_bytes == len(raw)

    # ~V, ~W, ~P: mnemonic (case preserved), unit, value text and description per line
    for items, key in (
        (log.version_section, "V"),
        (log.well_section, "W"),
        (log.parameter_section, "P"),
    ):
        ref = [_fields(ln) for ln in sec.get(key, [])]
        got = [(h.mnemonic, h.unit, h.value, h.description) for h in items]
        assert got == ref, key

    # ~C: mnemonic, unit, API code and description per curve, same order
    ref_c = [_fields(ln) for ln in sec["C"]]
    got_c = [
        (
            log.curves[n].mnemonic.split(":")[0],
            log.curves[n].unit_raw,
            log.curves[n].api_code,
            log.curves[n].description,
        )
        for n in log.curve_names
    ]
    assert got_c == ref_c

    # ~O verbatim (indentation and trailing spaces kept)
    assert log.other_section == other

    # ~A: same token count per curve, identical numbers, NaN exactly where == NULL
    tokens = " ".join(data_lines).split()
    assert len(tokens) % len(ref_c) == 0
    arr = np.array([float(t) for t in tokens]).reshape(-1, len(ref_c))
    assert np.array_equal(log.index, arr[:, 0])
    for j, n in enumerate(log.curve_names[1:], start=1):
        expected = arr[:, j].copy()
        if log.null_value is not None:
            expected[expected == log.null_value] = np.nan
        assert np.array_equal(log.curves[n].values, expected, equal_nan=True), n
    assert "HEADER_RAW_UNAVAILABLE" not in log.report.codes()


# --------------------------------------------------------------------- never alter values
@pytest.mark.parametrize(
    ("fname", "match"),
    [
        ("runon_dot.las", "run-on|not a number"),
        ("runon_hyphen.las", "run-on"),
        ("runon_real.las", "run-on"),
        ("text_numcol.las", "'abc' is not a number"),
        ("thousands.las", "comma inside a number"),
    ],
)
def test_ambiguous_tokens_are_refused_not_altered(fname: str, match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        read_las(PROB / fname, on_error="report")


def test_comma_decimal_public_file_refused() -> None:
    with pytest.raises(InputValidationError, match="comma inside a number"):
        read_las(DATA / "comma_decimal_mark.las", on_error="report")


def test_nan_tokens_and_missing_columns_are_not_called_null() -> None:
    nan = read_las(PROB / "nan_tok.las", on_error="report")
    assert "NAN_IN_DATA" in nan.report.codes()
    assert "NULL_SAMPLES" not in nan.report.codes()
    few = read_las(PROB / "fewer_cols.las", on_error="report")
    assert "CURVE_WITHOUT_DATA" in few.report.codes()


def test_case_preserved_and_lookup() -> None:
    low = read_las(PROB / "lower.las", on_error="report")
    assert "dt" in low.curve_names
    assert low.curve("DT").mnemonic == "dt"  # unique case-insensitive match
    assert low.curve("dt").mnemonic == "dt"


def test_null_variants() -> None:
    nd = read_las(PROB / "null_diff.las", on_error="report")
    assert "SUSPECT_SENTINEL" in nd.report.codes()
    na = read_las(PROB / "nullalpha.las", on_error="report")
    assert "NULL_NOT_NUMERIC" in na.report.codes() and "NULL_MISSING" not in na.report.codes()


def test_non_depth_index_gets_no_depth_alias() -> None:
    t = read_las(PROB / "timeidx.las", on_error="report")
    assert "DEPT" not in t.canonical_map
    assert "INDEX_NOT_DEPTH" in t.report.codes()


def test_encodings_are_reported() -> None:
    for f in ("mixed_enc.las", "cp1252dash.las"):
        r = read_las(PROB / f, on_error="report").report
        enc = next(c for c in r.checks if c.code == "ENCODING")
        assert enc.status == "warn" and "assumed" in enc.message
    be = read_las(PROB / "utf16be.las", on_error="report")
    assert "utf-16" in next(c for c in be.report.checks if c.code == "ENCODING").message


def test_duplicates_and_reversals_both_reported() -> None:
    r = read_las(PROB / "dupidx_neg.las", on_error="report").report
    assert r.status == "fail"


# --------------------------------------------------------------------- behaviour
def test_known_values_and_normalisation() -> None:
    log = read_las(DATA / "sample_2.0.las", on_error="raise")
    assert log.las_version == "2.0" and log.index_unit == "m" and log.null_value == -999.25
    assert log.index.tolist() == [1670.0, 1669.875, 1669.75]
    assert log.curve("RHOB").unit == "kg/m3"
    assert log.values_in("RHOB", "g/cc").tolist() == pytest.approx([2.55] * 3)
    assert log.values_in("DT", "us/ft").tolist() == pytest.approx([123.45 * 0.3048] * 3)
    assert log.curve("RDEEP").mnemonic == "ILD"
    assert log.index_in("ft")[0] == pytest.approx(1670.0 / 0.3048)
    assert log.well_section[0].value == "1670.0000" and log.well_section[0].value_parsed
    assert "MNEMONIC_MAPPED" in log.report.codes()
    assert log.report.status == "info"
    with pytest.raises(InputValidationError, match="no exact conversion"):
        log.values_in("RHOB", "us/ft")
    with pytest.raises(InputValidationError, match="available"):
        log.curve("XYZ")
    arr = log.curve("DT").values
    with pytest.raises(ValueError, match="read-only"):
        arr[0] = 0.0


def test_null_and_sentinel_handling() -> None:
    log = read_las(DATA / "missing_null.las", on_error="report")
    assert log.null_value is None and "NULL_MISSING" in log.report.codes()
    assert np.all(np.isfinite(log.curve("DT").values))  # -999.25 NOT replaced without NULL
    nul = read_las(DATA / "index_null.las", on_error="report")
    assert nul.index.tolist() == [999.0, 999.25, 999.5]  # index never nulled
    assert np.isnan(nul.curve("DT").values[0])
    assert "INDEX_EQUALS_NULL" in nul.report.codes()
    assert nul.valid_mask("DT", "NPHI").tolist() == [False, True, False]


def test_problem_files_are_reported() -> None:
    dup = read_las(DATA / "mnemonic_duplicate.las", on_error="report")
    assert "DUPLICATE_MNEMONIC" in dup.report.codes()
    hdr = read_las(DATA / "header_only.las", on_error="report")
    assert "NO_DATA" in hdr.report.codes() and hdr.index.size == 0
    ex = read_las(DATA / "excess_curves.las", on_error="report")
    assert "PARSER_WARNING" in ex.report.codes()
    mixed = read_las(DATA / "autodepthindex_M_FT.las", on_error="report")
    assert any("index units" in c.message.lower() for c in mixed.report.checks)
    assert "| Status |" in mixed.report.to_markdown()
    assert mixed.summary()["provenance"]["parser"] == "lasio"


def test_wrapped_file() -> None:
    w = read_las(DATA / "sample_2.0_wrapped.las", on_error="report")
    assert w.wrapped and "WRAPPED" in w.report.codes()
    assert w.curve("GR").values.size == w.index.size


def test_unsupported_versions_and_errors(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match="M0"):
        read_las(DATA / "sample_3.0.las", on_error="report")
    with pytest.raises(NotImplementedError, match="not supported"):
        read_las(DATA / "missing_vers.las", on_error="report")
    with pytest.raises(InputValidationError, match="cannot read"):
        read_las(tmp_path / "nope.las", on_error="report")
    with pytest.raises(InputValidationError, match="on_error"):
        read_las(DATA / "sample.las", on_error="ignore")  # type: ignore[arg-type]
    bad = tmp_path / "dup.las"
    txt = (DATA / "sample.las").read_text()
    head, data = txt.split("~A", 1)
    rows = data.splitlines()
    rows[2] = rows[1]
    bad.write_text(head + "~A" + "\n".join(rows) + "\n")
    with pytest.raises(InputValidationError, match="INDEX_DUPLICATES"):
        read_las(bad, on_error="raise")
    assert read_las(bad, on_error="report").report.status == "fail"


def test_irregular_and_header_mismatch(tmp_path: Path) -> None:
    txt = (DATA / "sample_2.0.las").read_text()
    head, _ = txt.split("~A", 1)
    f = tmp_path / "irr.las"
    f.write_text(
        head
        + "~A DEPTH DT RHOB NPHI SFLU SFLA ILM ILD\n"
        + "\n".join(f"{d} 1 2 3 4 5 6 7" for d in (1670.0, 1669.9, 1669.5, 1669.4))
        + "\n"
    )
    r = read_las(f, on_error="report").report
    assert {"IRREGULAR_SAMPLING", "HEADER_STOP_MISMATCH"} <= r.codes()
