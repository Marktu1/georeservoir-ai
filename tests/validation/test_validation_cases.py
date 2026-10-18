"""Validation cases from tests/validation/cases/*.json (see docs/validation/)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.validation.runner import FUNCTIONS, evaluate, is_runnable, load_cases

CASES = load_cases()


def test_case_ids_unique_and_well_formed() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    required = {"id", "module", "function", "kind", "description", "source", "source_status"}
    for c in CASES:
        assert required <= set(c), c["id"]
        assert c["function"] in FUNCTIONS, c["id"]
        assert c["source_status"] in {"confirmed", "fonte por verificar"}, c["id"]
        if is_runnable(c):
            assert c["tol_abs"] is not None and c["tol_rel"] is not None
            assert c["tolerance_justification"]


@pytest.mark.validation
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_validation_case(case: dict[str, Any]) -> None:
    if not is_runnable(case):
        pytest.skip(f"{case['id']}: fonte por verificar — not counted as validated")
    result = evaluate(case)
    assert result["passed"], f"{case['id']}: {result}"
