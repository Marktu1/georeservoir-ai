"""Upload endpoints: LAS and survey files through the API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import AUTH, PROJECT

DATA = Path(__file__).parents[1] / "data"
BASE = f"/api/v1/projects/{PROJECT}/data"
SURVEY_FORM = {
    "md_column": "MD_FT",
    "inclination_column": "INC_DEG",
    "azimuth_column": "AZI_DEG",
    "length_unit": "ft",
    "azimuth_reference": "true",
    "delimiter": ",",
    "start_east": "0",
    "start_north": "0",
    "start_tvd": "0",
}


def test_survey_upload_reproduces_published_trajectory(client: TestClient) -> None:
    with (DATA / "survey" / "bourgoyne_build.csv").open("rb") as f:
        r = client.post(
            f"{BASE}/survey",
            headers=AUTH,
            data=SURVEY_FORM,
            files={"file": ("bourgoyne_build.csv", f, "text/csv")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    traj = body["content"]["trajectory"]
    assert traj["maturity"] == "M3" and body["content"]["n_stations"] == 21
    assert traj["values"]["tvd_m"][-1] / 0.3048 == pytest.approx(1653.99, abs=0.005)
    assert body["provenance"]["file_name"] == "bourgoyne_build.csv"


def test_survey_errors_are_typed(client: TestClient) -> None:
    with (DATA / "survey" / "duplicate_md.csv").open("rb") as f:
        r = client.post(
            f"{BASE}/survey",
            headers=AUTH,
            data={
                **SURVEY_FORM,
                "md_column": "MD",
                "inclination_column": "INC",
                "azimuth_column": "AZI",
            },
            files={"file": ("d.csv", f, "text/csv")},
        )
    assert r.status_code == 422 and "strictly increasing" in r.json()["error"]["message"]
    r = client.post(
        f"{BASE}/survey",
        headers=AUTH,
        data={**SURVEY_FORM, "start_tvd": "nan"},
        files={"file": ("s.csv", b"MD_FT,INC_DEG,AZI_DEG\n0,0,0\n1,1,1\n")},
    )
    assert r.status_code == 422


def test_las_upload_nulls_become_json_null_and_versions(client: TestClient) -> None:
    with (DATA / "las" / "index_null.las").open("rb") as f:
        r = client.post(f"{BASE}/las", headers=AUTH, files={"file": ("x.las", f)})
    curves = {c["mnemonic"]: c for c in r.json()["content"]["curves"]}
    assert curves["DT"]["values"][0] is None and curves["DT"]["n_null"] == 1
    with (DATA / "las" / "sample_3.0.las").open("rb") as f:
        r = client.post(f"{BASE}/las", headers=AUTH, files={"file": ("x.las", f)})
    assert r.status_code == 501
    with (DATA / "las" / "sample_2.0.las").open("rb") as f:
        r = client.post(
            f"{BASE}/las",
            headers=AUTH,
            data={"include_data": "false"},
            files={"file": ("x.las", f)},
        )
    assert "values" not in r.json()["content"]["curves"][0]


def test_empty_upload_is_rejected(client: TestClient) -> None:
    r = client.post(f"{BASE}/las", headers=AUTH, files={"file": ("e.las", b"")})
    assert r.status_code == 422 and "empty" in r.json()["error"]["message"]
