"""Unit and property tests for the Bourdet derivative (spec §5.5)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from scipy.special import exp1

from georeservoir.common.exceptions import InputValidationError, NumericalError
from georeservoir.engineering.bourdet import bourdet_derivative

KW: dict[str, Any] = {"window_ln": 0.2, "sigma_p": 0.0, "pressure_unit": "psi"}


def deriv(t: Any, p: Any, **kw: Any) -> np.ndarray:
    return np.asarray(bourdet_derivative(t, p, **{**KW, **kw})["derivative"])


@st.composite
def series(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray]:
    n = draw(st.integers(5, 40))
    # steps >= 0.1 with n >= 5 give a span >= 0.4 = 2L, so every point has a neighbour
    steps = draw(st.lists(st.floats(0.1, 1.0), min_size=n - 1, max_size=n - 1))
    x = np.concatenate(([0.0], np.cumsum(steps))) + draw(st.floats(-5.0, 2.0))
    p = np.array(draw(st.lists(st.floats(-1e3, 1e3), min_size=n, max_size=n)))
    return np.exp(x), p


def test_storage_line_interior_bias_is_sinh_l_over_l() -> None:
    t = np.logspace(-3, 0, 31)  # log spacing h = ln(10)/10 > L, so neighbours are adjacent
    h = np.log(10.0) / 10.0
    d = deriv(t, 50.0 * t, window_ln=0.05)
    assert np.allclose(d[1:-1] / (50.0 * t[1:-1]), np.sinh(h) / h, rtol=1e-10)


@given(series(), st.floats(-1e4, 1e4))
def test_property_invariant_to_added_constant(s: tuple[np.ndarray, np.ndarray], c: float) -> None:
    t, p = s
    assert np.allclose(deriv(t, p + c), deriv(t, p), atol=1e-7 * (1 + abs(c)))


@given(series(), st.floats(1e-3, 1e3))
def test_property_time_unit_invariance(s: tuple[np.ndarray, np.ndarray], k: float) -> None:
    t, p = s
    assert np.allclose(deriv(t * k, p), deriv(t, p), rtol=1e-6, atol=1e-6)


@given(series(), series())
def test_property_linear_operator(
    s1: tuple[np.ndarray, np.ndarray], s2: tuple[np.ndarray, np.ndarray]
) -> None:
    t, p = s1
    q = s2[1][: p.size] if s2[1].size >= p.size else np.resize(s2[1], p.size)
    assert np.allclose(deriv(t, p + q), deriv(t, p) + deriv(t, q), atol=1e-6)


def test_sigma_propagation_matches_monte_carlo() -> None:
    rng = np.random.default_rng(20261018)
    t = np.logspace(-2, 1, 40)
    p = 30.0 * np.log(t) + 100.0
    rec = bourdet_derivative(t, p, window_ln=0.2, sigma_p=0.5, pressure_unit="psi")
    sims = np.array([deriv(t, p + rng.normal(0, 0.5, t.size)) for _ in range(4000)])
    assert np.allclose(sims.std(axis=0), rec["sigma_derivative"], rtol=0.08)


def test_line_source_derivative_matches_exponential() -> None:
    # Δp_D = −½ Ei(−1/(4 t_D)) = ½ E1(1/(4 t_D)); dΔp_D/d ln t_D = ½ exp(−1/(4 t_D))
    td = np.logspace(-1, 4, 200)
    pd = 0.5 * exp1(1.0 / (4.0 * td))
    d = deriv(td, pd, window_ln=0.1)
    ref = 0.5 * np.exp(-1.0 / (4.0 * td))
    inner = slice(5, -5)
    # Bourdet smoothing bias is O(L²); with L = 0.1 the error stays below 1 % here
    assert np.allclose(d[inner], ref[inner], rtol=0.01)


def test_one_sided_points_are_flagged() -> None:
    t = np.array([1.0, 1.1, 1.5, 2.0, 3.0, 5.0])
    r = bourdet_derivative(t, np.log(t), window_ln=0.3, sigma_p=0.0, pressure_unit="psi")
    side = r["side"].tolist()
    assert side[0] == 1.0 and side[-1] == -1.0 and 0.0 in side
    w = r.warnings[0]
    assert w.code == "ONE_SIDED_DERIVATIVE" and 0 in w.indices


@pytest.mark.parametrize(
    ("t", "p", "kw", "exc", "match"),
    [
        ([1.0, 2.0], [1.0, 2.0], {}, InputValidationError, "at least 3"),
        ([1.0, 1.0, 2.0], [1.0, 2.0, 3.0], {}, InputValidationError, "strictly increasing"),
        ([0.0, 1.0, 2.0], [1.0, 2.0, 3.0], {}, InputValidationError, "dt > 0"),
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0], {}, InputValidationError, "lengths differ"),
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], {"window_ln": 0.0}, InputValidationError, "window_ln"),
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], {"sigma_p": -1.0}, InputValidationError, "sigma_p"),
        (
            [1.0, 2.0, 3.0],
            [1.0, 2.0, 3.0],
            {"pressure_unit": "atm"},
            InputValidationError,
            "pressure_unit",
        ),
        ([1.0, 1.01, 1.02], [1.0, 2.0, 3.0], {"window_ln": 1.0}, NumericalError, "no neighbour"),
    ],
)
def test_invalid(
    t: list[float], p: list[float], kw: dict[str, Any], exc: type[Exception], match: str
) -> None:
    with pytest.raises(exc, match=match):
        bourdet_derivative(t, p, **{**KW, **kw})
