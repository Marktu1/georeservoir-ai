"""Unit and property tests for nodal analysis (spec §5.4)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from georeservoir.common.exceptions import InputValidationError, PhysicalConsistencyError
from georeservoir.engineering import nodal as nd

SOLVE: dict[str, Any] = {"pressure_unit": "psi", "n_grid": 400, "xtol": 1e-10, "maxiter": 200}


# --- IPR ------------------------------------------------------------------------
def test_linear_and_vogel_endpoints() -> None:
    lin = nd.ipr_linear([3000.0, 0.0], p_res=3000.0, j=0.5, pressure_unit="psi")
    assert lin["q"].tolist() == [0.0, 1500.0] and lin["q_max"] == 1500.0
    v = nd.ipr_vogel([2500.0, 0.0], p_res=2500.0, q_max=1000.0, pressure_unit="psi")
    assert v["q"].tolist() == [0.0, 1000.0]


def test_composite_continuity_at_bubble_point() -> None:
    m = nd.CompositeIPR(3000.0, 2130.0, 0.5)
    e = 1e-6
    q = m.rate(np.array([2130.0 - e, 2130.0, 2130.0 + e]))
    assert q[0] == pytest.approx(q[1], abs=1e-5) and q[2] == pytest.approx(q[1], abs=1e-5)
    slope_below = (q[1] - q[0]) / e
    slope_above = (q[2] - q[1]) / e
    assert slope_below == pytest.approx(-0.5, rel=1e-4)  # dq/dpwf = −J on both sides
    assert slope_above == pytest.approx(-0.5, rel=1e-4)


@st.composite
def ipr_models(draw: st.DrawFn) -> nd.IPRModel:
    pr = draw(st.floats(500.0, 8000.0))
    kind = draw(st.sampled_from(["lin", "vogel", "comp"]))
    if kind == "lin":
        return nd.LinearIPR(pr, draw(st.floats(0.01, 50.0)))
    if kind == "vogel":
        return nd.VogelIPR(pr, draw(st.floats(10.0, 1e5)))
    return nd.CompositeIPR(pr, draw(st.floats(0.05, 0.95)) * pr, draw(st.floats(0.01, 50.0)))


@given(ipr_models(), st.lists(st.floats(0.0, 1.0), min_size=2, max_size=40))
def test_property_ipr_monotone_and_invertible(m: nd.IPRModel, fr: list[float]) -> None:
    pwf = np.sort(np.array(fr)) * m.p_res
    q = m.rate(pwf)
    assert np.all(np.diff(q) <= 1e-9 * m.q_max)  # rate falls as pwf rises
    assert np.all((q >= -1e-9 * m.q_max) & (q <= m.q_max * (1 + 1e-12)))
    assert np.allclose(m.pwf(q), pwf, atol=1e-7 * m.p_res)  # inverse round trip


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: nd.ipr_linear([3100.0], p_res=3000.0, j=1.0, pressure_unit="psi"), "pwf"),
        (lambda: nd.ipr_vogel([-1.0], p_res=3000.0, q_max=1.0, pressure_unit="psi"), "pwf"),
        (lambda: nd.ipr_linear([1.0], p_res=3000.0, j=0.0, pressure_unit="psi"), "j"),
        (lambda: nd.ipr_linear([1.0], p_res=3000.0, j=1.0, pressure_unit="atm"), "pressure_unit"),
        (
            lambda: nd.vogel_qmax_from_test(
                p_res=2000.0, q_test=10.0, pwf_test=2000.0, pressure_unit="psi"
            ),
            "pwf_test",
        ),
        (
            lambda: nd.composite_j_from_test(
                p_res=3000.0, p_bubble=2000.0, q_test=10.0, pwf_test=3500.0, pressure_unit="psi"
            ),
            "pwf_test",
        ),
    ],
)
def test_invalid_inputs(call: Any, match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        call()


def test_composite_requires_undersaturated() -> None:
    with pytest.raises(PhysicalConsistencyError, match="p_res > p_bubble"):
        nd.ipr_composite([100.0], p_res=2000.0, p_bubble=2500.0, j=1.0, pressure_unit="psi")
    with pytest.raises(PhysicalConsistencyError):
        nd.composite_j_from_test(
            p_res=2000.0, p_bubble=2500.0, q_test=1.0, pwf_test=100.0, pressure_unit="psi"
        )


def test_composite_j_above_bubble_point() -> None:
    r = nd.composite_j_from_test(
        p_res=3000.0, p_bubble=2130.0, q_test=250.0, pwf_test=2500.0, pressure_unit="psi"
    )
    assert r["j"] == pytest.approx(0.5)


# --- TPR ------------------------------------------------------------------------
def test_tabulated_tpr_guards_and_no_extrapolation() -> None:
    t = nd.TabulatedTPR([0.0, 100.0, 200.0], [1000.0, 1100.0, 1300.0])
    assert t.pwf(np.array([100.0]))[0] == 1100.0
    with pytest.raises(InputValidationError, match="not extrapolated"):
        t.pwf(np.array([250.0]))
    with pytest.raises(InputValidationError, match="strictly increasing"):
        nd.TabulatedTPR([0.0, 0.0], [1.0, 2.0])
    with pytest.raises(InputValidationError, match="pwf > 0"):
        nd.TabulatedTPR([0.0, 1.0], [1.0, -2.0])
    with pytest.raises(InputValidationError, match="q >= 0"):
        nd.TabulatedTPR([-1.0, 1.0], [1.0, 2.0])


def test_multiphase_correlations_are_m0() -> None:
    with pytest.raises(NotImplementedError, match="M0"):
        nd.hagedorn_brown_tpr()
    with pytest.raises(NotImplementedError, match="M0"):
        nd.beggs_brill_tpr()


# --- solver -----------------------------------------------------------------------
def test_two_intersections_classified_unstable_then_stable() -> None:
    ipr = nd.LinearIPR(3000.0, 1.0)
    q = np.linspace(0.0, 2500.0, 26)
    # J-shaped TPR (liquid loading at low rate, friction at high rate)
    # f = IPR − TPR = −200 + 1.4q − 0.0012q²: roots 166.7 (unstable) and 1000 (stable)
    tpr = nd.TabulatedTPR(q, 3200.0 - 2.4 * q + 0.0012 * q**2)
    r = nd.nodal_solve(ipr, tpr, **SOLVE)
    assert r["n_solutions"] == 2
    assert r["stable"].tolist() == [0.0, 1.0]
    assert r["q_op"].tolist() == pytest.approx([500.0 / 3.0, 1000.0], rel=1e-3)
    assert np.allclose(ipr.pwf(r["q_op"]), r["pwf_op"], atol=1e-6)
    assert "MULTIPLE_SOLUTIONS" in {w.code for w in r.warnings}


def test_no_intersection_is_a_typed_result() -> None:
    ipr = nd.VogelIPR(2000.0, 500.0)
    tpr = nd.TabulatedTPR([0.0, 500.0], [2100.0, 2600.0])  # tubing always needs more
    r = nd.nodal_solve(ipr, tpr, **SOLVE)
    assert r["n_solutions"] == 0 and r["q_op"].size == 0
    assert {w.code for w in r.warnings} == {"NO_INTERSECTION"}


def test_tangency_is_flagged() -> None:
    ipr = nd.LinearIPR(3000.0, 1.0)
    q = np.linspace(0.0, 3000.0, 31)
    # touches the IPR from above at q = 1500 (no sign change)
    tpr = nd.TabulatedTPR(q, (3000.0 - q) + 1e-4 * (q - 1500.0) ** 2 + 1e-9)
    r = nd.nodal_solve(ipr, tpr, **{**SOLVE, "n_grid": 301})
    assert "POSSIBLE_TANGENCY" in {w.code for w in r.warnings}


@pytest.mark.parametrize(
    ("kw", "match"),
    [({"n_grid": 5}, "n_grid"), ({"maxiter": 0}, "maxiter"), ({"xtol": 0.0}, "xtol")],
)
def test_solver_settings_validated(kw: dict[str, Any], match: str) -> None:
    ipr = nd.LinearIPR(3000.0, 1.0)
    tpr = nd.TabulatedTPR([0.0, 3000.0], [1000.0, 2000.0])
    with pytest.raises(InputValidationError, match=match):
        nd.nodal_solve(ipr, tpr, **{**SOLVE, **kw})


def test_non_overlapping_ranges_rejected() -> None:
    ipr = nd.LinearIPR(1000.0, 0.1)  # q_max = 100
    tpr = nd.TabulatedTPR([200.0, 300.0], [500.0, 600.0])
    with pytest.raises(InputValidationError, match="do not overlap"):
        nd.nodal_solve(ipr, tpr, **SOLVE)


@given(st.floats(1000.0, 6000.0), st.floats(0.1, 5.0), st.floats(0.05, 0.6), st.floats(0.0, 2.0))
def test_property_linear_solver_matches_algebra(
    pr: float, j: float, frac: float, c: float
) -> None:
    a = frac * pr
    qmax = j * pr
    q = np.linspace(0.0, qmax, 5)
    r = nd.nodal_solve(nd.LinearIPR(pr, j), nd.TabulatedTPR(q, a + c * q), **SOLVE)
    q_star = (pr - a) / (1 / j + c)
    assert r["n_solutions"] == 1 and r["stable"][0] == 1.0
    assert r["q_op"][0] == pytest.approx(q_star, rel=1e-8, abs=1e-8)


# --- review fixes -------------------------------------------------------------------
def test_tangency_flagged_even_with_another_root() -> None:
    ipr = nd.LinearIPR(3000.0, 1.0)
    q = np.linspace(0.0, 2600.0, 131)
    # g = TPR − IPR: touches 0 at q = 1000 (no crossing), then crosses 0 near q = 2440
    g = np.where(q < 1800.0, 1e-4 * (q - 1000.0) ** 2 + 1e-6, 64.0 - 0.1 * (q - 1800.0))
    tpr = nd.TabulatedTPR(q, (3000.0 - q) + g)
    r = nd.nodal_solve(ipr, tpr, **{**SOLVE, "n_grid": 1301})
    assert r["n_solutions"] == 1 and r["q_op"][0] == pytest.approx(2440.0, rel=1e-3)
    assert "POSSIBLE_TANGENCY" in {w.code for w in r.warnings}


def test_zero_rate_intersection_warns() -> None:
    ipr = nd.LinearIPR(3000.0, 1.0)
    r = nd.nodal_solve(ipr, nd.TabulatedTPR([0.0, 3000.0], [3000.0, 6000.0]), **SOLVE)
    assert r["q_op"].tolist() == [0.0]
    assert "ZERO_RATE_INTERSECTION" in {w.code for w in r.warnings}


def test_truncated_table_message() -> None:
    ipr = nd.LinearIPR(3000.0, 1.0)
    tpr = nd.TabulatedTPR([0.0, 1000.0], [3100.0, 2500.0])  # ends before AOF = 3000
    r = nd.nodal_solve(ipr, tpr, **SOLVE)
    w = r.warnings[0]
    assert w.code == "NO_INTERSECTION" and "extend the table" in w.message


def test_ipr_inverse_refuses_rates_outside_range() -> None:
    for m in (
        nd.LinearIPR(3000.0, 1.0),
        nd.VogelIPR(2500.0, 1000.0),
        nd.CompositeIPR(3000.0, 2000.0, 1.0),
    ):
        with pytest.raises(InputValidationError, match="q_max"):
            m.pwf(np.array([m.q_max * 1.01]))
