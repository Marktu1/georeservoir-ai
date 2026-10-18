"""Survey reader tests, including an end-to-end published case (file → trajectory)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from georeservoir.common.exceptions import InputValidationError
from georeservoir.io.survey import read_survey

DATA = Path(__file__).parents[1] / "data" / "survey"
CSV: dict[str, Any] = {
    "md_column": "MD_FT",
    "inclination_column": "INC_DEG",
    "azimuth_column": "AZI_DEG",
    "length_unit": "ft",
    "azimuth_reference": "true",
    "delimiter": ",",
}


def test_file_to_published_trajectory() -> None:
    """Bourgoyne et al. (1991) build example read from a CSV file: TVD 1653.99 ft and
    North 954.93 ft at MD 2000 ft (published to 0.01 ft → ±0.005 ft)."""
    path = DATA / "bourgoyne_build.csv"
    s = read_survey(path, **CSV)
    assert s.provenance.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert s.md.size == 21 and s.source_lines[0] == 5
    t = s.trajectory(start_east=0.0, start_north=0.0, start_tvd=0.0)
    ft = 0.3048
    assert t["tvd_m"][-1] / ft == pytest.approx(1653.99, abs=0.005)
    assert t["north_m"][-1] / ft == pytest.approx(954.93, abs=0.005)
    assert s.report.status == "info"


def test_whitespace_comments_tiein_and_normalisation() -> None:
    s = read_survey(
        DATA / "whitespace_tiein.txt",
        md_column="md",
        inclination_column="inc",
        azimuth_column="azi",
        length_unit="m",
        azimuth_reference="grid",
        delimiter="whitespace",
    )
    assert s.md.tolist() == [100.0, 200.0, 300.0] and s.source_lines == (2, 4, 5)
    assert {"FIRST_STATION_NOT_AT_ZERO", "AZIMUTH_NORMALISED"} <= s.report.codes()


@pytest.mark.parametrize(
    ("fname", "kw", "match"),
    [
        (
            "missing_value.csv",
            {
                "delimiter": ";",
                "md_column": "md",
                "inclination_column": "inc",
                "azimuth_column": "azi",
            },
            "line 3.*missing",
        ),
        (
            "duplicate_md.csv",
            {"md_column": "MD", "inclination_column": "INC", "azimuth_column": "AZI"},
            "line 4.*strictly increasing",
        ),
        ("bourgoyne_build.csv", {"md_column": "DEPTH"}, "found 0 time"),
        ("bourgoyne_build.csv", {"length_unit": "yd"}, "length_unit"),
        ("bourgoyne_build.csv", {"azimuth_reference": "north"}, "azimuth_reference"),
        ("bourgoyne_build.csv", {"delimiter": "|"}, "delimiter"),
        ("nope.csv", {}, "cannot read"),
    ],
)
def test_errors(fname: str, kw: dict[str, Any], match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        read_survey(DATA / fname, **{**CSV, **kw})


def test_bad_number_and_inclination(tmp_path: Path) -> None:
    f = tmp_path / "s.csv"
    f.write_text("MD_FT,INC_DEG,AZI_DEG\n0,0,0\n100,abc,0\n")
    with pytest.raises(InputValidationError, match=r"line 3.*not a number"):
        read_survey(f, **CSV)
    f.write_text("MD_FT,INC_DEG,AZI_DEG\n0,0,0\n100,190,0\n")
    with pytest.raises(InputValidationError, match=r"line 3.*outside"):
        read_survey(f, **CSV)
    f.write_text("MD_FT,INC_DEG,AZI_DEG\n0,0,0\n")
    with pytest.raises(InputValidationError, match="at least 2"):
        read_survey(f, **CSV)
    f.write_text("MD_FT,INC_DEG,AZI_DEG\n0,0,0\n10,1,0\n20,2,0\n30,3,0\n1000,4,0\n")
    assert "LARGE_STATION_GAP" in read_survey(f, **CSV).report.codes()
