"""Unit and property tests for petrophysics (spec §5.2)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from georeservoir.common.exceptions import (
    InputValidationError,
    NumericalError,
    PhysicalConsistencyError,
)
from georeservoir.common.record import CalculationRecord
from georeservoir.engineering import petrophysics as pp

VSH: list[tuple[Callable[..., CalculationRecord], float]] = [
    # (function, documented value at IGR = 1)
    (pp.vsh_larionov_tertiary, 0.083 * (2**3.7 - 1)),
    (pp.vsh_larionov_older, 0.99),
    (pp.vsh_steiber, 1.0),
    (pp.vsh_clavier, 1.0),
]
EPS = 1e-12  # float64 rounding allowance (A-007)
unit_interval = st.floats(0.0, 1.0)


# --- gamma-ray index ----------------------------------------------------------
def test_igr_out_of_range_warns_and_optionally_clips() -> None:
    r = pp.gamma_ray_index([10, 50, 130], gr_min_api=20, gr_max_api=120, clip=False)
    assert r["igr_raw"].tolist() == pytest.approx([-0.1, 0.3, 1.1])
    assert r["igr"].tolist() == r["igr_raw"].tolist()
    assert r["n_clipped"] == 0
    assert r.warnings[0].code == "OUT_OF_RANGE_RAW" and r.warnings[0].indices == (0, 2)
    c = pp.gamma_ray_index([10, 50, 130], gr_min_api=20, gr_max_api=120, clip=True)
    assert c["igr"].tolist() == pytest.approx([0.0, 0.3, 1.0])
    assert c["n_clipped"] == 2


def test_igr_rejects_bad_baselines() -> None:
    with pytest.raises(InputValidationError, match="gr_max_api"):
        pp.gamma_ray_index([50], gr_min_api=100, gr_max_api=100, clip=False)


# --- Vsh ----------------------------------------------------------------------
@pytest.mark.parametrize(("fn", "at_one"), VSH)
def test_vsh_endpoints(fn: Callable[..., CalculationRecord], at_one: float) -> None:
    v = fn([0.0, 1.0])["vsh"]
    assert v[0] == pytest.approx(0.0, abs=EPS)
    assert v[1] == pytest.approx(at_one, abs=EPS)


@pytest.mark.parametrize(("fn", "_"), VSH)
def test_vsh_rejects_igr_outside_unit_interval(
    fn: Callable[..., CalculationRecord], _: float
) -> None:
    with pytest.raises(InputValidationError, match=r"igr\[1\]"):
        fn([0.5, 1.2])


@pytest.mark.parametrize(("fn", "_"), VSH)
@given(xs=st.lists(unit_interval, min_size=2, max_size=50))
def test_vsh_properties(fn: Callable[..., CalculationRecord], _: float, xs: list[float]) -> None:
    x = np.sort(np.array(xs))
    v = fn(x)["vsh"]
    assert np.all(np.isfinite(v))
    assert np.all(np.diff(v) >= -EPS)  # monotone non-decreasing
    assert np.all(v <= x + EPS)  # Vsh ≤ IGR on [0, 1]
    assert np.all(v >= -EPS)


# --- porosity -----------------------------------------------------------------
def test_density_porosity_behaviour() -> None:
    r = pp.density_porosity(
        [2.65, 1.0, 2.80], rho_matrix_g_cc=2.65, rho_fluid_g_cc=1.0, clip=False
    )
    assert r["porosity"][:2].tolist() == pytest.approx([0.0, 1.0])
    assert r.warnings[0].indices == (2,)
    with pytest.raises(PhysicalConsistencyError):
        pp.density_porosity([2.3], rho_matrix_g_cc=1.0, rho_fluid_g_cc=1.0, clip=False)
    with pytest.raises(InputValidationError, match=r"rho_bulk_g_cc\[0\]"):
        pp.density_porosity([-1.0], rho_matrix_g_cc=2.65, rho_fluid_g_cc=1.0, clip=False)


def test_sonic_porosity_behaviour() -> None:
    r = pp.sonic_porosity_wyllie(
        [55.5, 189.0, 40.0], dt_matrix_us_per_ft=55.5, dt_fluid_us_per_ft=189.0, clip=True
    )
    assert r["porosity"].tolist() == pytest.approx([0.0, 1.0, 0.0])
    assert r["n_clipped"] == 1
    with pytest.raises(PhysicalConsistencyError):
        pp.sonic_porosity_wyllie(
            [80.0], dt_matrix_us_per_ft=189.0, dt_fluid_us_per_ft=55.5, clip=False
        )


@given(st.floats(1.0, 2.65))
def test_density_porosity_monotone_decreasing(rb: float) -> None:
    a = pp.density_porosity([rb, rb + 0.01], rho_matrix_g_cc=2.71, rho_fluid_g_cc=1.0, clip=False)[
        "porosity"
    ]
    assert a[1] < a[0]


# --- Archie -------------------------------------------------------------------
ARCHIE = {"rw_ohm_m": 0.04, "a": 0.81, "m": 2.0, "n": 2.0}


def test_archie_sw_equals_one_at_wet_resistivity() -> None:
    phi = 0.25
    r0 = ARCHIE["a"] * ARCHIE["rw_ohm_m"] / phi ** ARCHIE["m"]
    r = pp.archie_water_saturation([phi], [r0], clip=False, **ARCHIE)
    assert r["sw"][0] == pytest.approx(1.0, abs=1e-14)
    assert not r.warnings


def test_archie_sw_above_one_warns_and_clips() -> None:
    r = pp.archie_water_saturation([0.2], [0.1], clip=True, **ARCHIE)
    assert r["sw_raw"][0] > 1.0 and r["sw"][0] == 1.0 and r["n_clipped"] == 1


@pytest.mark.parametrize(
    ("phi", "rt", "kw", "match"),
    [
        ([0.0], [10.0], {}, r"porosity\[0\]"),
        ([1.2], [10.0], {}, r"porosity\[0\]"),
        ([0.2], [0.0], {}, r"rt_ohm_m\[0\]"),
        ([0.2], [10.0], {"m": 0.0}, "m: received"),
        ([0.2, 0.3], [10.0, 20.0, 30.0], {}, "equal lengths"),
    ],
)
def test_archie_invalid(
    phi: list[float], rt: list[float], kw: dict[str, float], match: str
) -> None:
    with pytest.raises(InputValidationError, match=match):
        pp.archie_water_saturation(phi, rt, clip=False, **{**ARCHIE, **kw})


def test_archie_broadcasting() -> None:
    r = pp.archie_water_saturation([0.2], [5.0, 10.0, 20.0], clip=False, **ARCHIE)
    assert r["sw"].shape == (3,)
    r2 = pp.archie_water_saturation([0.1, 0.2], [10.0], clip=False, **ARCHIE)
    assert r2["sw"].shape == (2,)


def test_archie_inverse_rejects_bad_sw() -> None:
    with pytest.raises(InputValidationError, match=r"sw\[0\]"):
        pp.archie_true_resistivity([0.2], [0.0], **ARCHIE)


@given(st.floats(0.02, 0.4), st.floats(0.05, 1.0), st.floats(1.5, 2.5), st.floats(1.5, 2.5))
def test_archie_round_trip(phi: float, sw: float, m: float, n: float) -> None:
    p = {**ARCHIE, "m": m, "n": n}
    rt = pp.archie_true_resistivity([phi], [sw], **p)["rt_ohm_m"]
    back = pp.archie_water_saturation([phi], rt, clip=False, **p)["sw"]
    assert back[0] == pytest.approx(sw, rel=1e-12)


@given(
    st.floats(0.02, 0.4), st.lists(st.floats(0.1, 2000.0), min_size=2, max_size=30, unique=True)
)
def test_archie_monotone_decreasing_in_rt(phi: float, rts: list[float]) -> None:
    rt = np.sort(np.array(rts))
    sw = pp.archie_water_saturation([phi], rt, clip=False, **ARCHIE)["sw_raw"]
    assert np.all(np.diff(sw) < 0)


# --- numerical safety (adversarial review) -------------------------------------
@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # NumPy overflow, then our NumericalError
def test_non_finite_outputs_raise_numerical_error() -> None:
    with pytest.raises(NumericalError, match="not finite"):
        pp.archie_water_saturation([1e-160], [10.0], clip=False, **ARCHIE)
    with pytest.raises(NumericalError, match="not finite"):
        pp.gamma_ray_index([1e300], gr_min_api=0.0, gr_max_api=1e-300, clip=False)


def test_clip_must_be_bool() -> None:
    with pytest.raises(InputValidationError, match="clip"):
        pp.gamma_ray_index([50.0], gr_min_api=20, gr_max_api=120, clip="no")  # type: ignore[arg-type]
