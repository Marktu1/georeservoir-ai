"""Shared logic for validation cases: load JSON, run, measure error.

Used by ``test_validation_cases.py`` (assertions) and by
``scripts/build_validation_report.py`` (report table).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from georeservoir.engineering import dca, nodal, petrophysics, well_path

CASES_DIR = Path(__file__).parent / "cases"

FUNCTIONS: dict[str, Callable[..., Any]] = {
    "well_path.minimum_curvature": well_path.minimum_curvature,
    "petrophysics.gamma_ray_index": petrophysics.gamma_ray_index,
    "petrophysics.vsh_steiber": petrophysics.vsh_steiber,
    "petrophysics.vsh_larionov_older": petrophysics.vsh_larionov_older,
    "petrophysics.vsh_larionov_tertiary": petrophysics.vsh_larionov_tertiary,
    "petrophysics.vsh_clavier": petrophysics.vsh_clavier,
    "petrophysics.density_porosity": petrophysics.density_porosity,
    "petrophysics.sonic_porosity_wyllie": petrophysics.sonic_porosity_wyllie,
    "petrophysics.archie_water_saturation": petrophysics.archie_water_saturation,
    "dca.arps_rate": dca.arps_rate,
    "dca.arps_cumulative": dca.arps_cumulative,
    "dca.nominal_to_effective_decline": dca.nominal_to_effective_decline,
    "nodal.ipr_vogel": nodal.ipr_vogel,
    "nodal.vogel_qmax_from_test": nodal.vogel_qmax_from_test,
    "nodal.ipr_composite": nodal.ipr_composite,
    "nodal.composite_j_from_test": nodal.composite_j_from_test,
    "nodal.nodal_solve_linear": lambda p_res, j, tpr_q, tpr_pwf: nodal.nodal_solve(
        nodal.LinearIPR(p_res, j),
        nodal.TabulatedTPR(tpr_q, tpr_pwf),
        pressure_unit="psi",
        n_grid=100,
        xtol=1e-10,
        maxiter=200,
    ),
}


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]


def is_runnable(case: dict[str, Any]) -> bool:
    has_data = case["expected"] is not None or case.get("per_row") is not None
    return case["source_status"] == "confirmed" and has_data


def _rows(case: dict[str, Any]) -> list[dict[str, Any]]:
    """A case is one (kwargs, expected) pair or a list of them under ``per_row``."""
    if case.get("per_row") is not None:
        rows: list[dict[str, Any]] = case["per_row"]
        return rows
    return [{"kwargs": case["kwargs"], "expected": case["expected"]}]


def evaluate(case: dict[str, Any]) -> dict[str, Any]:
    """Run a case. Returns max abs error, max allowed error and pass flag."""
    max_err = 0.0
    passed = True
    worst_ratio = 0.0
    index = case.get("expected_index")
    maturity = ""
    for row in _rows(case):
        record = FUNCTIONS[case["function"]](**row["kwargs"])
        maturity = record.maturity
        r = _compare(case, record, row["expected"], index)
        if r is None:
            return {
                "max_abs_error": float("inf"),
                "error_to_tolerance": float("inf"),
                "passed": False,
                "maturity": maturity,
            }
        max_err = max(max_err, r[0])
        worst_ratio = max(worst_ratio, r[1])
        passed = passed and r[2]
    return {
        "max_abs_error": max_err,
        "error_to_tolerance": worst_ratio,
        "passed": passed,
        "maturity": maturity,
    }


def _compare(
    case: dict[str, Any], record: Any, expected_map: dict[str, Any], index: int | None
) -> tuple[float, float, bool] | None:
    max_err = 0.0
    worst_ratio = 0.0
    passed = True
    for key, expected in expected_map.items():
        got = np.atleast_1d(np.asarray(record[key], dtype=np.float64))
        if index is not None:
            got = got[[index]]
        exp = np.asarray(expected, dtype=np.float64)
        if got.shape != exp.shape:
            return None
        err = np.abs(got - exp)
        allowed = case["tol_abs"] + case["tol_rel"] * np.abs(exp)
        max_err = max(max_err, float(err.max(initial=0.0)))
        worst_ratio = max(worst_ratio, float((err / allowed).max(initial=0.0)))
        passed = passed and bool(np.all(err <= allowed))
    return max_err, worst_ratio, passed
