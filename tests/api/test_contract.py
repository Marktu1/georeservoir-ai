"""Contract tests: every endpoint returns exactly the core library's CalculationRecord.

For each endpoint the response ``record`` must equal ``to_dict()`` of a direct call to
the core function with the same inputs (same values, units, inputs_hash, maturity,
warnings). The OpenAPI document must match the committed snapshot (docs/api).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from georeservoir.common.record import CalculationRecord
from georeservoir.engineering import (
    bourdet,
    dca,
    material_balance,
    nodal,
    petrophysics,
    uncertainty,
    well_path,
)
from tests.api.conftest import AUTH, PROJECT

BASE = f"/api/v1/projects/{PROJECT}/calc"
SNAPSHOT = Path(__file__).parents[2] / "docs" / "api" / "openapi-v1.json"
PVT: dict[str, Any] = {
    "bo_rb_stb": [1.30, 1.29, 1.28],
    "bg_rb_scf": [0.00090, 0.00095, 0.00100],
    "rs_scf_stb": [600.0, 570.0, 540.0],
}
EXP = material_balance.expansion_terms(
    [3300.0, 3150.0, 3000.0],
    pi_psia=3330.0,
    boi_rb_stb=1.31,
    bgi_rb_scf=0.00087,
    rsi_scf_stb=630.0,
    cw_per_psi=3e-6,
    cf_per_psi=4e-6,
    swi=0.2,
    m=0.4,
    **PVT,
)
EO, EG, EFW = (EXP[k].tolist() for k in ("eo", "eg", "efw"))
F_KNOWN = [5e7 * (a + 0.4 * b + c) for a, b, c in zip(EO, EG, EFW, strict=True)]
T = list(range(1, 25))
Q_FIT = dca.arps_rate(T, qi=800.0, di=0.12, b=0.6, time_unit="month", d_terminal=None)[
    "q"
].tolist()

CASES: list[tuple[str, dict[str, Any], Callable[[], CalculationRecord]]] = [
    (
        "well-path/minimum-curvature",
        {
            "md": [0, 100, 200],
            "inclination_deg": [0, 10, 20],
            "azimuth_deg": [0, 45, 45],
            "length_unit": "m",
            "azimuth_reference": "true",
            "start_east": 0,
            "start_north": 0,
            "start_tvd": 0,
        },
        lambda: well_path.minimum_curvature(
            [0, 100, 200],
            [0, 10, 20],
            [0, 45, 45],
            length_unit="m",
            azimuth_reference="true",
            start_east=0,
            start_north=0,
            start_tvd=0,
        ),
    ),
    (
        "petrophysics/gamma-ray-index",
        {"gr_api": [10, 60, 130], "gr_min_api": 20, "gr_max_api": 120, "clip": True},
        lambda: petrophysics.gamma_ray_index(
            [10, 60, 130], gr_min_api=20, gr_max_api=120, clip=True
        ),
    ),
    (
        "petrophysics/vsh",
        {"igr": [0.1, 0.5, 0.9], "method": "clavier"},
        lambda: petrophysics.vsh_clavier([0.1, 0.5, 0.9]),
    ),
    (
        "petrophysics/vsh",
        {"igr": [0.1, 0.5, 0.9], "method": "larionov_tertiary"},
        lambda: petrophysics.vsh_larionov_tertiary([0.1, 0.5, 0.9]),
    ),
    (
        "petrophysics/density-porosity",
        {
            "rho_bulk_g_cc": [2.4, 2.3],
            "rho_matrix_g_cc": 2.65,
            "rho_fluid_g_cc": 1.0,
            "clip": False,
        },
        lambda: petrophysics.density_porosity(
            [2.4, 2.3], rho_matrix_g_cc=2.65, rho_fluid_g_cc=1.0, clip=False
        ),
    ),
    (
        "petrophysics/sonic-porosity-wyllie",
        {
            "dt_us_per_ft": [80, 90],
            "dt_matrix_us_per_ft": 55.5,
            "dt_fluid_us_per_ft": 189,
            "clip": False,
        },
        lambda: petrophysics.sonic_porosity_wyllie(
            [80, 90], dt_matrix_us_per_ft=55.5, dt_fluid_us_per_ft=189, clip=False
        ),
    ),
    (
        "petrophysics/archie-sw",
        {
            "porosity": [0.2],
            "rt_ohm_m": [20, 5],
            "rw_ohm_m": 0.05,
            "a": 1,
            "m": 2,
            "n": 2,
            "clip": True,
        },
        lambda: petrophysics.archie_water_saturation(
            [0.2], [20, 5], rw_ohm_m=0.05, a=1, m=2, n=2, clip=True
        ),
    ),
    (
        "petrophysics/archie-rt",
        {"porosity": [0.2], "sw": [0.25], "rw_ohm_m": 0.05, "a": 1, "m": 2, "n": 2},
        lambda: petrophysics.archie_true_resistivity([0.2], [0.25], rw_ohm_m=0.05, a=1, m=2, n=2),
    ),
    (
        "dca/rate",
        {
            "t": [0, 12, 24],
            "qi": 1000,
            "di": 0.1,
            "b": 1.2,
            "time_unit": "month",
            "d_terminal": 0.005,
        },
        lambda: dca.arps_rate(
            [0, 12, 24], qi=1000, di=0.1, b=1.2, time_unit="month", d_terminal=0.005
        ),
    ),
    (
        "dca/cumulative",
        {"t": [12, 24], "qi": 1000, "di": 0.1, "b": 0.5, "time_unit": "month", "d_terminal": None},
        lambda: dca.arps_cumulative(
            [12, 24], qi=1000, di=0.1, b=0.5, time_unit="month", d_terminal=None
        ),
    ),
    (
        "dca/eur",
        {
            "qi": 1000,
            "di": 0.1,
            "b": 0.5,
            "time_unit": "month",
            "d_terminal": None,
            "q_limit": 5,
            "t_horizon": None,
        },
        lambda: dca.arps_eur(
            qi=1000, di=0.1, b=0.5, time_unit="month", d_terminal=None, q_limit=5, t_horizon=None
        ),
    ),
    (
        "dca/fit",
        {"t": T, "q": Q_FIT, "include": [True] * len(T), "time_unit": "month"},
        lambda: dca.arps_fit(T, Q_FIT, include=np.ones(len(T), bool), time_unit="month"),
    ),
    (
        "dca/nominal-to-effective",
        {"values": [0.1, 0.5], "b": 0.5},
        lambda: dca.nominal_to_effective_decline([0.1, 0.5], b=0.5),
    ),
    (
        "dca/effective-to-nominal",
        {"values": [0.1, 0.5], "b": 0.0},
        lambda: dca.effective_to_nominal_decline([0.1, 0.5], b=0.0),
    ),
    (
        "nodal/ipr",
        {"model": "vogel", "pwf": [500.0], "p_res": 2000, "pressure_unit": "psi", "q_max": 162},
        lambda: nodal.ipr_vogel([500.0], p_res=2000, q_max=162, pressure_unit="psi"),
    ),
    (
        "nodal/ipr",
        {
            "model": "composite",
            "pwf": [2500, 1000],
            "p_res": 3000,
            "p_bubble": 2130,
            "j": 0.5,
            "pressure_unit": "psi",
        },
        lambda: nodal.ipr_composite(
            [2500, 1000], p_res=3000, p_bubble=2130, j=0.5, pressure_unit="psi"
        ),
    ),
    (
        "nodal/ipr",
        {"model": "linear", "pwf": [500.0], "p_res": 2000, "j": 0.13, "pressure_unit": "psi"},
        lambda: nodal.ipr_linear([500.0], p_res=2000, j=0.13, pressure_unit="psi"),
    ),
    (
        "nodal/vogel-qmax-from-test",
        {"p_res": 2000, "q_test": 65, "pwf_test": 1500, "pressure_unit": "psi"},
        lambda: nodal.vogel_qmax_from_test(
            p_res=2000, q_test=65, pwf_test=1500, pressure_unit="psi"
        ),
    ),
    (
        "nodal/composite-j-from-test",
        {
            "p_res": 3000,
            "p_bubble": 2130,
            "q_test": 630.7,
            "pwf_test": 1700,
            "pressure_unit": "psi",
        },
        lambda: nodal.composite_j_from_test(
            p_res=3000, p_bubble=2130, q_test=630.7, pwf_test=1700, pressure_unit="psi"
        ),
    ),
    (
        "nodal/solve",
        {
            "ipr": {
                "model": "linear",
                "pwf": [0.0],
                "p_res": 3000,
                "j": 0.5,
                "pressure_unit": "psi",
            },
            "tpr_q": [0, 500, 1000, 1500],
            "tpr_pwf": [1200, 1600, 2000, 2400],
            "n_grid": 100,
            "xtol": 1e-10,
            "maxiter": 200,
        },
        lambda: nodal.nodal_solve(
            nodal.LinearIPR(3000, 0.5),
            nodal.TabulatedTPR([0, 500, 1000, 1500], [1200, 1600, 2000, 2400]),
            pressure_unit="psi",
            n_grid=100,
            xtol=1e-10,
            maxiter=200,
        ),
    ),
    (
        "bourdet/derivative",
        {
            "dt": [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0],
            "dp": [1, 2, 3, 4, 5, 6, 7],
            "window_ln": 0.2,
            "sigma_p": 0.1,
            "pressure_unit": "psi",
        },
        lambda: bourdet.bourdet_derivative(
            [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0],
            [1, 2, 3, 4, 5, 6, 7],
            window_ln=0.2,
            sigma_p=0.1,
            pressure_unit="psi",
        ),
    ),
    (
        "material-balance/underground-withdrawal",
        {
            "np_stb": [1e5],
            "rp_scf_stb": [800],
            "wp_stb": [2e3],
            "bo_rb_stb": [1.25],
            "bg_rb_scf": [0.001],
            "rs_scf_stb": [500],
            "bw_rb_stb": [1.02],
        },
        lambda: material_balance.underground_withdrawal(
            [1e5],
            [800],
            [2e3],
            bo_rb_stb=[1.25],
            bg_rb_scf=[0.001],
            rs_scf_stb=[500],
            bw_rb_stb=[1.02],
        ),
    ),
    (
        "material-balance/expansion-terms",
        {
            "p_psia": [3300.0, 3150.0, 3000.0],
            **PVT,
            "pi_psia": 3330.0,
            "boi_rb_stb": 1.31,
            "bgi_rb_scf": 0.00087,
            "rsi_scf_stb": 630.0,
            "cw_per_psi": 3e-6,
            "cf_per_psi": 4e-6,
            "swi": 0.2,
            "m": 0.4,
        },
        lambda: EXP,
    ),
    (
        "material-balance/fit-known-m",
        {"f_rb": F_KNOWN, "eo": EO, "eg": EG, "efw": EFW, "m": 0.4, "we_rb": None},
        lambda: material_balance.fit_known_m(F_KNOWN, EO, EG, EFW, m=0.4, we_rb=None),
    ),
    (
        "material-balance/fit-no-cap-no-aquifer",
        {"f_rb": F_KNOWN, "eo": EO, "efw": EFW, "we_rb": [0, 0, 0]},
        lambda: material_balance.fit_no_cap_no_aquifer(F_KNOWN, EO, EFW, we_rb=[0, 0, 0]),
    ),
    (
        "material-balance/fit-gas-cap-unknown-m",
        {
            "f_rb": [3e7 * (a + 0.7 * b) for a, b in zip(EO, EG, strict=True)],
            "eo": EO,
            "eg": EG,
            "we_rb": None,
        },
        lambda: material_balance.fit_gas_cap_unknown_m(
            [3e7 * (a + 0.7 * b) for a, b in zip(EO, EG, strict=True)], EO, EG, we_rb=None
        ),
    ),
    (
        "uncertainty/mc-archie-sw",
        {
            "porosity": {"kind": "triangular", "low": 0.15, "mode": 0.2, "high": 0.25},
            "rt_ohm_m": {"kind": "lognormal", "median": 20, "sigma_ln": 0.2},
            "rw_ohm_m": {"kind": "fixed", "value": 0.05},
            "a": {"kind": "fixed", "value": 1},
            "m": {"kind": "uniform", "low": 1.8, "high": 2.2},
            "n": {"kind": "fixed", "value": 2},
            "clip": True,
            "n_samples": 2000,
            "seed": 7,
        },
        lambda: uncertainty.mc_archie_sw(
            porosity=uncertainty.Triangular(0.15, 0.2, 0.25),
            rt_ohm_m=uncertainty.LogNormal(20, 0.2),
            rw_ohm_m=uncertainty.Fixed(0.05),
            a=uncertainty.Fixed(1),
            m=uncertainty.Uniform(1.8, 2.2),
            n=uncertainty.Fixed(2),
            clip=True,
            n_samples=2000,
            seed=7,
            return_samples=False,
        ),
    ),
    (
        "uncertainty/mc-arps-eur",
        {
            "qi": {"kind": "normal", "mean": 1000, "sd": 100, "low": 500, "high": None},
            "di": {"kind": "uniform", "low": 0.08, "high": 0.15},
            "b": {"kind": "fixed", "value": 0.5},
            "time_unit": "month",
            "d_terminal": None,
            "q_limit": 10,
            "t_horizon": None,
            "n_samples": 500,
            "seed": 3,
        },
        lambda: uncertainty.mc_arps_eur(
            qi=uncertainty.Normal(1000, 100, 500, None),
            di=uncertainty.Uniform(0.08, 0.15),
            b=uncertainty.Fixed(0.5),
            time_unit="month",
            d_terminal=None,
            q_limit=10,
            t_horizon=None,
            n_samples=500,
            seed=3,
            return_samples=False,
        ),
    ),
]


@pytest.mark.parametrize(
    ("path", "payload", "direct"), CASES, ids=[f"{c[0]}#{i}" for i, c in enumerate(CASES)]
)
def test_endpoint_returns_core_record(
    client: TestClient, path: str, payload: dict[str, Any], direct: Callable[[], CalculationRecord]
) -> None:
    r = client.post(f"{BASE}/{path}", headers=AUTH, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_version"] == "v1" and body["project_id"] == PROJECT
    expected = json.loads(direct().to_json())  # JSON round trip, as on the wire
    assert body["record"] == expected


def test_every_calc_route_is_covered(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    calc = {p.split("/calc/")[1] for p in spec["paths"] if "/calc/" in p}
    assert calc == {c[0] for c in CASES}


def test_methods_listing_reports_core_maturity(client: TestClient) -> None:
    rows = client.get(f"/api/v1/projects/{PROJECT}/methods", headers=AUTH).json()
    by = {r["method"]: r["maturity"] for r in rows}
    assert by["georeservoir.engineering.well_path.minimum_curvature"] == "M3"
    assert by["georeservoir.engineering.dca.arps_rate"] == "M2"
    assert all(r["maturity"] in {"M0", "M1", "M2", "M3"} for r in rows)


def test_openapi_matches_committed_snapshot(client: TestClient) -> None:
    """The public contract changes only deliberately: regenerate the snapshot with
    ``python scripts/export_openapi.py`` and review the diff."""
    spec = client.get("/api/v1/openapi.json").json()
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    spec["info"].pop("version")
    snap["info"].pop("version")
    assert spec == snap


def test_typed_errors(client: TestClient) -> None:
    r = client.post(
        f"{BASE}/petrophysics/vsh", headers=AUTH, json={"igr": [1.5], "method": "steiber"}
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["type"] == "InputValidationError" and "igr[0]: received 1.5" in err["message"]
    assert err["request_id"] == r.headers["x-request-id"]
    r = client.post(
        f"{BASE}/nodal/ipr",
        headers=AUTH,
        json={
            "model": "composite",
            "pwf": [100],
            "p_res": 2000,
            "p_bubble": 2500,
            "j": 1,
            "pressure_unit": "psi",
        },
    )
    assert r.json()["error"]["type"] == "PhysicalConsistencyError"
    r = client.post(
        f"{BASE}/nodal/ipr",
        headers=AUTH,
        json={"model": "vogel", "pwf": [100], "p_res": 2000, "pressure_unit": "psi"},
    )
    assert r.status_code == 422 and "q_max" in r.json()["error"]["message"]


def test_health_is_public_and_minimal(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and set(r.json()) == {"status", "api_version", "library_version"}
