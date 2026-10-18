"""Tests for Monte Carlo uncertainty propagation (P90/P50/P10, PRMS convention)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from scipy.stats import norm

from georeservoir.common.exceptions import InputValidationError
from georeservoir.engineering import dca, petrophysics
from georeservoir.engineering import uncertainty as u

ARCHIE: dict[str, Any] = {
    "porosity": u.Fixed(0.2),
    "rt_ohm_m": u.Fixed(20.0),
    "rw_ohm_m": u.Fixed(0.05),
    "a": u.Fixed(1.0),
    "m": u.Fixed(2.0),
    "n": u.Fixed(2.0),
    "clip": False,
    "n_samples": 1000,
    "seed": 1,
    "return_samples": False,
}
EUR: dict[str, Any] = {
    "qi": u.Fixed(1000.0),
    "di": u.Fixed(0.1),
    "b": u.Fixed(0.5),
    "time_unit": "month",
    "d_terminal": None,
    "q_limit": None,
    "t_horizon": 120.0,
    "n_samples": 1000,
    "seed": 1,
    "return_samples": False,
}


def test_fixed_inputs_reproduce_deterministic_results() -> None:
    r = u.mc_archie_sw(**ARCHIE)
    det = petrophysics.archie_water_saturation(
        [0.2], [20.0], rw_ohm_m=0.05, a=1.0, m=2.0, n=2.0, clip=False
    )["sw"][0]
    for k in ("sw_p90_low", "sw_p50", "sw_p10_high", "sw_mean"):
        assert r[k] == pytest.approx(det, rel=1e-15)
    e = u.mc_arps_eur(**EUR)
    det_e = dca.arps_eur(
        qi=1000.0, di=0.1, b=0.5, time_unit="month", d_terminal=None, q_limit=None, t_horizon=120.0
    )["eur"]
    assert e["eur_p50"] == pytest.approx(det_e, rel=1e-15)


def test_reproducible_with_seed() -> None:
    kw = {**ARCHIE, "rt_ohm_m": u.LogNormal(20.0, 0.3), "m": u.Uniform(1.8, 2.2)}
    a, b = u.mc_archie_sw(**kw), u.mc_archie_sw(**kw)
    assert a.to_json() == b.to_json() and a.inputs_hash == b.inputs_hash
    c = u.mc_archie_sw(**{**kw, "seed": 2})
    assert c["sw_p50"] != a["sw_p50"] and c.inputs_hash != a.inputs_hash


def test_quantiles_map_through_monotone_archie() -> None:
    # Sw decreases with Rt (others fixed): Sw quantiles are Sw(Rt quantiles), mirrored.
    sigma, n = 0.3, 400_000
    r = u.mc_archie_sw(**{**ARCHIE, "rt_ohm_m": u.LogNormal(20.0, sigma), "n_samples": n})
    z = norm.ppf(0.9)

    def sw(rt: float) -> float:
        return float(np.sqrt(0.05 / (0.04 * rt)))

    # order-statistic s.e. of ln(Rt) quantiles ≈ 1.7σ/√n ≈ 8e-4 → Sw relative ≈ 4e-4
    assert r["sw_p50"] == pytest.approx(sw(20.0), rel=3e-3)
    assert r["sw_p90_low"] == pytest.approx(sw(20.0 * np.exp(z * sigma)), rel=3e-3)
    assert r["sw_p10_high"] == pytest.approx(sw(20.0 * np.exp(-z * sigma)), rel=3e-3)
    assert r["sw_p90_low"] < r["sw_p50"] < r["sw_p10_high"]


def test_quantiles_map_through_linear_eur() -> None:
    n = 200_000
    e = u.mc_arps_eur(**{**EUR, "qi": u.Uniform(500.0, 1500.0), "n_samples": n})
    k = dca.arps_eur(
        qi=1.0, di=0.1, b=0.5, time_unit="month", d_terminal=None, q_limit=None, t_horizon=120.0
    )["eur"]  # EUR is proportional to qi
    assert e["eur_p90_low"] == pytest.approx(600.0 * k, rel=5e-3)
    assert e["eur_p50"] == pytest.approx(1000.0 * k, rel=5e-3)
    assert e["eur_p10_high"] == pytest.approx(1400.0 * k, rel=5e-3)


def test_samples_and_clip_warning() -> None:
    r = u.mc_archie_sw(
        **{**ARCHIE, "rt_ohm_m": u.Uniform(0.5, 3.0), "clip": True, "return_samples": True}
    )
    s = r["sw_samples"]
    assert s.shape == (1000,) and s.max() <= 1.0
    assert r.warnings[0].code == "OUT_OF_RANGE_RAW"


def test_eur_with_terminal_decline_and_rate_limit() -> None:
    e = u.mc_arps_eur(
        **{
            **EUR,
            "b": u.Triangular(0.5, 1.0, 1.5),
            "d_terminal": 0.005,
            "q_limit": 5.0,
            "t_horizon": None,
        }
    )
    assert 0 < e["eur_p90_low"] < e["eur_p50"] < e["eur_p10_high"]
    assert "B_GREATER_THAN_ONE" in {w.code for w in e.warnings}


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"n_samples": 10}, "n_samples"),
        ({"n_samples": True}, "n_samples"),
        ({"seed": -1}, "seed"),
        ({"clip": "yes"}, "clip"),
        ({"porosity": u.Uniform(-0.1, 0.2)}, "porosity"),
        ({"rt_ohm_m": u.Normal(1.0, 5.0, low=None, high=None)}, "rt_ohm_m"),
        ({"porosity": 0.2}, "Distribution"),
    ],
)
def test_archie_invalid(kw: dict[str, Any], match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        u.mc_archie_sw(**{**ARCHIE, **kw})


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"b": u.Uniform(0.5, 1.5)}, "d_terminal"),
        ({"b": u.Uniform(1.5, 2.5), "d_terminal": 0.01}, "b: some"),
        ({"qi": u.Uniform(-1.0, 1.0)}, "qi/di"),
        ({"t_horizon": None}, "at least one"),
        ({"q_limit": 2000.0}, "q_limit"),
        ({"time_unit": "week"}, "time_unit"),
    ],
)
def test_eur_invalid(kw: dict[str, Any], match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        u.mc_arps_eur(**{**EUR, **kw})


def test_distribution_validation_and_truncation() -> None:
    with pytest.raises(InputValidationError):
        u.Uniform(1.0, 1.0)
    with pytest.raises(InputValidationError):
        u.Triangular(0.0, 2.0, 1.0)
    with pytest.raises(InputValidationError):
        u.Normal(0.0, 1.0, low=1.0, high=0.0)
    with pytest.raises(InputValidationError):
        u.LogNormal(0.0, 0.1)
    with pytest.raises(InputValidationError):
        u.Fixed(float("nan"))
    rng = np.random.default_rng(0)
    s = u.Normal(0.2, 0.05, low=0.15, high=0.25).sample(rng, 5000)
    assert s.min() >= 0.15 and s.max() <= 0.25 and s.size == 5000
    with pytest.raises(InputValidationError, match="probability mass"):
        u.Normal(0.0, 1e-3, low=10.0, high=10.0 + 1e-9).sample(rng, 10)
    assert "Normal" in u.Normal(0.0, 1.0, low=None, high=None).describe()
