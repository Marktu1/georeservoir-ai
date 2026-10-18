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

from georeservoir.engineering import petrophysics, well_path

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
}


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]


def is_runnable(case: dict[str, Any]) -> bool:
    return case["source_status"] == "confirmed" and case["expected"] is not None


def evaluate(case: dict[str, Any]) -> dict[str, Any]:
    """Run a case. Returns max abs error, max allowed error and pass flag."""
    record = FUNCTIONS[case["function"]](**case["kwargs"])
    max_err = 0.0
    passed = True
    worst_ratio = 0.0
    for key, expected in case["expected"].items():
        got = np.asarray(record[key], dtype=np.float64)
        exp = np.asarray(expected, dtype=np.float64)
        if got.shape != exp.shape:
            return {"max_abs_error": float("inf"), "passed": False, "maturity": record.maturity}
        err = np.abs(got - exp)
        allowed = case["tol_abs"] + case["tol_rel"] * np.abs(exp)
        max_err = max(max_err, float(err.max(initial=0.0)))
        worst_ratio = max(worst_ratio, float((err / allowed).max(initial=0.0)))
        passed = passed and bool(np.all(err <= allowed))
    return {
        "max_abs_error": max_err,
        "error_to_tolerance": worst_ratio,
        "passed": passed,
        "maturity": record.maturity,
    }
