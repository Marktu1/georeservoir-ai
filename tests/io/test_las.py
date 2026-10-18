"""LAS reader tests, including the Phase 2 gate: public files read without metadata loss.

The metadata/data check uses an **independent** minimal parser written here (plain text
splitting, NumPy for numbers) — it does not call lasio or georeservoir — so the gate is not
a circular oracle.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from georeservoir.common.exceptions import InputValidationError
from georeservoir.io.las import read_las

DATA = Path(__file__).parents[1] / "data" / "las"
# Well-formed public LAS 1.2/2.0 files (lasio test suite, MIT licence) used for the gate.
GATE_FILES = [
    "sample.las",
    "sample_2.0.las",
    "sample_2.0_wrapped.las",
    "sample_2.0_minimal.las",
    "sample_curve_api.las",
    "missing_null.las",
    "encodings_cp1252.las",
    "encodings_utf16le.las",
]


# --------------------------------------------------------------------- independent parser
def _text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            t = raw.decode(enc)
            if "~" in t:
                return t
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def _sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cur = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("~"):
            cur = s[1].upper()
            out.setdefault(cur, [])
            continue
        if cur and s and not s.startswith("#"):
            out[cur].append(line)
    return out


def _header_mnemonics(lines: list[str]) -> list[str]:
    return [ln.split(".", 1)[0].strip().upper() for ln in lines]


def _header_value(line: str) -> str:
    after_dot = line.split(".", 1)[1]
    unit_and_value = after_dot.rsplit(":", 1)[0]
    parts = (
        unit_and_value.split(None, 1) if not unit_and_value[:1].isspace() else ["", unit_and_value]
    )
    return (parts[1] if len(parts) > 1 else "").strip()


def _data(lines: list[str], n_curves: int, null: float | None) -> np.ndarray:
    tokens = " ".join(lines).replace("\t", " ").split()
    arr = np.array([float(t) for t in tokens], dtype=np.float64).reshape(-1, n_curves)
    if null is not None:
        body = arr[:, 1:]
        body[body == null] = np.nan
    return arr


# --------------------------------------------------------------------- gate
@pytest.mark.parametrize("name", GATE_FILES)
def test_gate_no_metadata_or_data_loss(name: str) -> None:
    path = DATA / name
    log = read_las(path, on_error="report")
    sec = _sections(_text(path))

    # provenance: hash of the exact bytes
    assert log.provenance.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert log.provenance.size_bytes == path.stat().st_size

    # every header line of ~V, ~W, ~P, ~C is present, in order
    assert [h.mnemonic.upper() for h in log.version_section] == _header_mnemonics(sec["V"])
    assert [h.mnemonic.upper() for h in log.well_section] == _header_mnemonics(sec["W"])
    assert [h.mnemonic.upper() for h in log.parameter_section] == _header_mnemonics(
        sec.get("P", [])
    )
    raw_curves = _header_mnemonics(sec["C"])
    assert [n.split(":")[0] for n in log.curve_names] == raw_curves

    # header values are kept verbatim (string comparison, numbers not re-formatted)
    for section, key in (
        (log.version_section, "V"),
        (log.well_section, "W"),
        (log.parameter_section, "P"),
    ):
        for item, line in zip(section, sec.get(key, []), strict=True):
            assert item.value == _header_value(line), item.mnemonic
    assert "HEADER_RAW_UNAVAILABLE" not in log.report.codes()

    # ~O free text preserved
    assert " ".join(log.other_section.split()) == " ".join(" ".join(sec.get("O", [])).split())

    # data: identical to an independent tokenisation, NaN exactly where value == NULL
    ref = _data(sec["A"], len(raw_curves), log.null_value)
    assert np.array_equal(log.index, ref[:, 0])
    for j, n in enumerate(log.curve_names[1:], start=1):
        assert np.array_equal(log.curves[n].values, ref[:, j], equal_nan=True), n


# --------------------------------------------------------------------- behaviour
def test_known_values_and_normalisation() -> None:
    log = read_las(DATA / "sample_2.0.las", on_error="raise")
    assert log.las_version == "2.0" and log.index_unit == "m" and log.null_value == -999.25
    assert log.index.tolist() == [1670.0, 1669.875, 1669.75]
    assert log.curve("RHOB").unit == "kg/m3"
    assert log.values_in("RHOB", "g/cc").tolist() == pytest.approx([2.55] * 3)
    assert log.values_in("DT", "us/ft").tolist() == pytest.approx([123.45 * 0.3048] * 3)
    assert log.curve("RDEEP").mnemonic == "ILD"  # canonical alias
    assert log.index_in("ft")[0] == pytest.approx(1670.0 / 0.3048)
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
    assert log.null_value is None
    assert "NULL_MISSING" in log.report.codes()
    assert np.all(np.isfinite(log.curve("DT").values))  # -999.25 NOT replaced without NULL
    nul = read_las(DATA / "index_null.las", on_error="report")
    assert nul.index.tolist() == [999.0, 999.25, 999.5]  # index never nulled
    assert np.isnan(nul.curve("DT").values[0])
    assert "INDEX_EQUALS_NULL" in nul.report.codes()
    assert nul.valid_mask("DT", "NPHI").tolist() == [False, True, False]


def test_problem_files_are_reported() -> None:
    comma = read_las(DATA / "comma_decimal_mark.las", on_error="report")
    assert "DECIMAL_COMMA" in comma.report.codes()
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
    rows[2] = rows[1]  # duplicate the first depth row
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
