"""Unit and property tests for Arps DCA (spec §5.3)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from scipy.integrate import quad

from georeservoir.common.exceptions import IdentifiabilityError, InputValidationError
from georeservoir.engineering import dca

P: dict[str, Any] = {"qi": 1000.0, "di": 0.1, "time_unit": "month", "d_terminal": None}
b_st = st.floats(0.0, 2.0)


def rate(t: Any, b: float, **kw: Any) -> np.ndarray:
    return np.asarray(dca.arps_rate(t, **{**P, "b": b, **kw})["q"])


def cum(t: Any, b: float, **kw: Any) -> np.ndarray:
    return np.asarray(dca.arps_cumulative(t, **{**P, "b": b, **kw})["np"])


# --- rate & cumulative --------------------------------------------------------
def test_initial_values() -> None:
    assert rate([0.0], 0.7)[0] == 1000.0
    assert cum([0.0], 0.7)[0] == 0.0


@pytest.mark.parametrize("b0", [0.0, 1.0])
def test_continuity_in_b(b0: float) -> None:
    t = np.array([1.0, 12.0, 120.0])
    for eps in (1e-6, 1e-9):
        for bb in (b0 + eps, max(b0 - eps, 0.0)):
            assert np.allclose(rate(t, bb), rate(t, b0), rtol=1e-4)
            assert np.allclose(cum(t, bb), cum(t, b0), rtol=1e-4)


@given(b_st, st.floats(0.01, 2.0), st.floats(0.5, 300.0))
def test_property_cumulative_is_integral_of_rate(b: float, di: float, t: float) -> None:
    def q(x: float) -> float:
        return float(rate([x], b, di=di)[0])

    ref = quad(q, 0.0, t, epsabs=1e-10, epsrel=1e-10, limit=200)[0]
    assert cum([t], b, di=di)[0] == pytest.approx(ref, rel=1e-7, abs=1e-6)


@given(b_st, st.lists(st.floats(0.0, 500.0), min_size=2, max_size=30, unique=True))
def test_property_monotone(b: float, ts: list[float]) -> None:
    t = np.sort(np.array(ts))
    q, n = rate(t, b), cum(t, b)
    # non-strict: times closer than float64 resolution give equal values
    assert np.all(np.diff(q) <= 0) and np.all(np.diff(n) >= 0)
    assert np.all(n <= 1000.0 * t + 1e-9)  # cumulative never exceeds qi·t


def test_b_greater_than_one_warns() -> None:
    r = dca.arps_rate([1.0], **{**P, "b": 1.5})
    assert [w.code for w in r.warnings] == ["B_GREATER_THAN_ONE"]


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"b": 2.5}, "b: received"),
        ({"b": -0.1}, "b: received"),
        ({"qi": 0.0}, "qi"),
        ({"di": -1.0}, "di"),
        ({"time_unit": "week"}, "time_unit"),
        ({"d_terminal": 0.0}, "d_terminal"),
    ],
)
def test_invalid(kw: dict[str, Any], match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        dca.arps_rate([1.0], **{**P, "b": 0.5, **kw})
    with pytest.raises(InputValidationError, match=r"t\[0\]"):
        dca.arps_rate([-1.0], **{**P, "b": 0.5})


# --- modified hyperbolic -------------------------------------------------------
def test_modified_hyperbolic_switch_is_continuous() -> None:
    kw = {"di": 0.2, "d_terminal": 0.01}
    rec = dca.arps_rate([0.0], **{**P, "b": 1.2, **kw})
    ts = float(rec["switch_time"])
    assert ts == pytest.approx((0.2 / 0.01 - 1) / (1.2 * 0.2))
    e = 1e-7
    t = np.array([ts - e, ts, ts + e])
    q, n = rate(t, 1.2, **kw), cum(t, 1.2, **kw)
    assert q[0] == pytest.approx(q[2], rel=1e-6)
    assert n[2] - n[0] == pytest.approx(2 * e * q[1], rel=1e-3)  # dNp = q·dt across the switch
    # after the switch the instantaneous decline equals d_terminal
    t2 = np.array([ts + 10.0, ts + 10.0 + 1e-4])
    q2 = rate(t2, 1.2, **kw)
    assert -np.log(q2[1] / q2[0]) / 1e-4 == pytest.approx(0.01, rel=1e-5)
    # before the switch it matches pure Arps
    assert rate([ts / 2], 1.2, **kw)[0] == pytest.approx(rate([ts / 2], 1.2, di=0.2)[0])


def test_modified_with_terminal_above_initial_is_exponential() -> None:
    q = rate([10.0], 0.8, di=0.05, d_terminal=0.08)
    assert q[0] == pytest.approx(1000.0 * np.exp(-0.8))


@given(b_st, st.floats(0.01, 0.5), st.floats(0.0005, 0.009))
def test_property_modified_integral(b: float, di: float, dmin: float) -> None:
    def q(x: float) -> float:
        return float(rate([x], b, di=di, d_terminal=dmin)[0])

    t = 600.0
    ts = float(dca.arps_rate([0.0], **{**P, "b": b, "di": di, "d_terminal": dmin})["switch_time"])
    pts = [ts] if 0 < ts < t else None
    ref = quad(q, 0.0, t, epsabs=1e-9, epsrel=1e-10, limit=400, points=pts)[0]
    assert cum([t], b, di=di, d_terminal=dmin)[0] == pytest.approx(ref, rel=1e-7)


# --- EUR ------------------------------------------------------------------------
def test_eur_rate_limit_matches_cumulative() -> None:
    # last two: terminal decline ≥ Di (pure exponential); limit reached before the switch
    cases = [
        (0.0, None, 5.0),
        (0.6, None, 5.0),
        (1.3, 0.005, 5.0),
        (0.6, 0.02, 5.0),
        (0.6, 0.2, 5.0),
        (1.3, 0.005, 900.0),
    ]
    for b, dmin, ql in cases:
        e = dca.arps_eur(
            qi=1000.0, di=0.1, b=b, time_unit="month", d_terminal=dmin, q_limit=ql, t_horizon=None
        )
        assert e["q_end"] == pytest.approx(ql, rel=1e-10)
        assert e["eur"] == pytest.approx(cum([e["t_end"]], b, d_terminal=dmin)[0], rel=1e-12)


def test_eur_uses_earliest_cutoff_and_guards() -> None:
    e = dca.arps_eur(
        qi=1000.0, di=0.1, b=0.5, time_unit="month", d_terminal=None, q_limit=1.0, t_horizon=24.0
    )
    assert e["t_end"] == 24.0
    with pytest.raises(InputValidationError, match="d_terminal"):
        dca.arps_eur(
            qi=1000.0,
            di=0.1,
            b=1.0,
            time_unit="month",
            d_terminal=None,
            q_limit=1.0,
            t_horizon=None,
        )
    with pytest.raises(InputValidationError, match="at least one"):
        dca.arps_eur(
            qi=1000.0,
            di=0.1,
            b=0.5,
            time_unit="month",
            d_terminal=None,
            q_limit=None,
            t_horizon=None,
        )
    with pytest.raises(InputValidationError, match="q_limit < qi"):
        dca.arps_eur(
            qi=1000.0,
            di=0.1,
            b=0.5,
            time_unit="month",
            d_terminal=None,
            q_limit=2000.0,
            t_horizon=None,
        )


# --- conversions ------------------------------------------------------------------
@given(st.floats(1e-4, 50.0), b_st)
def test_property_effective_round_trip(d: float, b: float) -> None:
    de = dca.nominal_to_effective_decline([d], b=b)["d_effective"]
    if de[0] >= 1.0:  # float64 saturation for very large exponential declines
        return
    back = dca.effective_to_nominal_decline(de, b=b)["d_nominal"][0]
    # conditioning: recovering D needs 1 − De, which carries ~eps/(1 − De) relative error
    rel = 1e-9 + 1e-15 / (1.0 - float(de[0]))
    assert back == pytest.approx(d, rel=rel)


def test_effective_guards_and_period_conversion() -> None:
    with pytest.raises(InputValidationError, match="d_effective"):
        dca.effective_to_nominal_decline([1.0], b=0.5)
    with pytest.raises(InputValidationError, match="d_nominal"):
        dca.nominal_to_effective_decline([0.0], b=0.5)
    y = dca.convert_nominal_decline([0.01], from_unit="month", to_unit="year")["d_nominal"]
    assert y[0] == pytest.approx(0.12)
    d = dca.convert_nominal_decline([0.12], from_unit="year", to_unit="day")["d_nominal"]
    assert d[0] == pytest.approx(0.12 / 365.25)


# --- fitting ------------------------------------------------------------------------
T = np.arange(1.0, 61.0)


@pytest.mark.parametrize("b", [0.0, 0.4, 0.9, 1.4])
def test_fit_recovers_exact_curve(b: float) -> None:
    q = rate(T, b, di=0.12, qi=800.0)
    f = dca.arps_fit(T, q, include=np.ones(T.size, bool), time_unit="month")
    assert f["qi"] == pytest.approx(800.0, rel=1e-6)
    assert f["di"] == pytest.approx(0.12, rel=1e-5)
    assert f["b"] == pytest.approx(b, abs=1e-5)
    assert f["converged"] == 1 and f["r2"] > 0.999999


def test_fit_with_noise_within_standard_errors() -> None:
    rng = np.random.default_rng(20261018)
    q = rate(T, 0.8, di=0.12, qi=800.0) * np.exp(rng.normal(0, 0.03, T.size))
    f = dca.arps_fit(T, q, include=np.ones(T.size, bool), time_unit="month")
    for k, true in (("qi", 800.0), ("di", 0.12), ("b", 0.8)):
        assert abs(f[k] - true) < 4 * f[f"{k}_se"], k


def test_fit_requires_mask_for_shut_ins() -> None:
    q = rate(T, 0.5, di=0.1).copy()  # records are read-only
    q[[10, 11]] = 0.0
    with pytest.raises(InputValidationError, match=r"q\[10\]"):
        dca.arps_fit(T, q, include=np.ones(T.size, bool), time_unit="month")
    mask = np.ones(T.size, bool)
    mask[[10, 11]] = False
    f = dca.arps_fit(T, q, include=mask, time_unit="month")
    assert f["b"] == pytest.approx(0.5, abs=1e-5)
    assert any(w.code == "POINTS_EXCLUDED" and w.indices == (10, 11) for w in f.warnings)


def test_fit_guards() -> None:
    q = rate(T, 0.5)
    with pytest.raises(InputValidationError, match="include"):
        dca.arps_fit(T, q, include=np.ones(T.size), time_unit="month")
    with pytest.raises(IdentifiabilityError, match="at least 4"):
        dca.arps_fit(T[:3], q[:3], include=np.ones(3, bool), time_unit="month")
    with pytest.raises(InputValidationError, match="strictly increasing"):
        dca.arps_fit(T[::-1], q, include=np.ones(T.size, bool), time_unit="month")


def test_fit_flags_b_at_bound() -> None:
    q = rate(T, 0.0, di=0.12)  # pure exponential: b converges to the 0 bound
    f = dca.arps_fit(
        T,
        q * np.exp(np.linspace(0, 0.02, T.size)),
        include=np.ones(T.size, bool),
        time_unit="month",
    )
    codes = {w.code for w in f.warnings}
    assert "B_AT_BOUND" in codes or f["b"] > 1e-8


def test_terminal_above_initial_warns() -> None:
    r = dca.arps_rate([1.0], qi=1000.0, di=0.05, b=0.5, time_unit="month", d_terminal=0.1)
    assert "TERMINAL_DECLINE_EXCEEDS_INITIAL" in {w.code for w in r.warnings}


def test_bool_refused_as_number() -> None:
    with pytest.raises(InputValidationError, match="qi"):
        dca.arps_rate([1.0], qi=True, di=0.1, b=0.5, time_unit="month", d_terminal=None)
