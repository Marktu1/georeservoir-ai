"""Unit and property tests for Minimum Curvature (spec §5.1)."""

from __future__ import annotations

from typing import Any

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
from georeservoir.engineering.well_path import (
    RF_TAYLOR_THRESHOLD_RAD,
    dogleg_angle,
    minimum_curvature,
    normalize_azimuth,
    ratio_factor,
)

BASE: dict[str, Any] = {
    "length_unit": "m",
    "azimuth_reference": "true",
    "start_east": 0.0,
    "start_north": 0.0,
    "start_tvd": 0.0,
}


def mc(md: Any, inc: Any, azi: Any, **kw: Any) -> CalculationRecord:
    return minimum_curvature(md, inc, azi, **{**BASE, **kw})


# --- unit tests ---------------------------------------------------------------
def test_vertical_well_warns_closure_undefined() -> None:
    r = mc([0, 100, 200], [0, 0, 0], [10, 200, 300])
    assert np.allclose(r["tvd_m"], [0, 100, 200])
    assert [w.code for w in r.warnings] == ["CLOSURE_AZIMUTH_UNDEFINED"]
    assert r.warnings[0].indices == (1, 2)


def test_azimuth_wrap_359_to_1_is_2_degrees() -> None:
    r = mc([0, 30], [90, 90], [359, 1])
    assert r["dogleg_deg"][0] == pytest.approx(2.0, abs=1e-12)
    assert r["north_m"][-1] > 29.9  # heads north, not round the compass


def test_inclination_zero_any_azimuth_gives_same_path() -> None:
    a = mc([0, 50, 100], [0, 0, 10], [0, 0, 45])
    b = mc([0, 50, 100], [0, 0, 10], [123, 271, 45])
    for k in ("north_m", "east_m", "tvd_m"):
        assert np.allclose(a[k], b[k], atol=1e-12)


def test_feet_input_scales_to_metres() -> None:
    m = mc([0, 1000, 2000], [0, 20, 40], [0, 30, 60])
    f = mc(np.array([0, 1000, 2000]) / 0.3048, [0, 20, 40], [0, 30, 60], length_unit="ft")
    assert np.allclose(m["tvd_m"], f["tvd_m"], rtol=1e-13, atol=1e-12)
    assert np.allclose(m["dls_deg_per_30m"], f["dls_deg_per_30m"], rtol=1e-13, atol=0)
    assert np.allclose(
        m["dls_deg_per_100ft"], m["dls_deg_per_30m"] * (100 * 0.3048 / 30), rtol=1e-14, atol=0
    )


def test_start_offset_shifts_coordinates() -> None:
    r = mc([100, 200], [10, 10], [90, 90], start_east=5, start_north=-3, start_tvd=99)
    assert r["md_m"][0] == 100 and r["tvd_m"][0] == 99
    assert r["east_m"][0] == 5 and r["north_m"][0] == -3
    assert r["closure_azimuth_deg"][1] == pytest.approx(90.0)


def test_record_metadata() -> None:
    r = mc([0, 100], [0, 5], [0, 0])
    assert r.method == "well_path.minimum_curvature"
    assert r.maturity == "M3"
    assert "SPE-84246-PA" in r.method_reference
    assert r.inputs["azimuth_reference"] == "true"
    assert r["dogleg_deg"].shape == (1,)


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"md": [0]}, "at least 2"),
        ({"md": [0, 0]}, "strictly increasing"),
        ({"inc": [0, 181]}, r"inclination_deg\[1\]"),
        ({"inc": [-1, 0]}, r"inclination_deg\[0\]"),
        ({"azi": [0, np.nan]}, "finite"),
        ({"inc": [0, 1, 2]}, "lengths differ"),
        ({"length_unit": "yd"}, "length unit"),
        ({"azimuth_reference": "north"}, "azimuth_reference"),
        ({"start_tvd": np.inf}, "start_tvd"),
    ],
)
def test_invalid_inputs(kw: dict[str, Any], match: str) -> None:
    md = kw.pop("md", [0, 100])
    inc = kw.pop("inc", [0, 10])
    azi = kw.pop("azi", [0, 0])
    with pytest.raises(InputValidationError, match=match):
        mc(md, inc, azi, **kw)


def test_reversal_is_physically_inconsistent() -> None:
    with pytest.raises(PhysicalConsistencyError, match="reversal"):
        mc([0, 100], [0, 180], [0, 0])


def test_ratio_factor_taylor_boundary_continuity() -> None:
    t = RF_TAYLOR_THRESHOLD_RAD
    below = ratio_factor(np.array([np.nextafter(t, 0.0)]))[0]
    above = ratio_factor(np.array([t]))[0]
    assert below == pytest.approx(above, abs=1e-15)
    assert ratio_factor(np.array([0.0]))[0] == 1.0


def test_beta_near_zero_matches_trapezoid_oracle() -> None:
    i1, i2, az, dmd = np.radians(10.0), np.radians(10.0 + 1e-9), np.radians(45.0), 100.0
    b = mc([0, dmd], [10, 10 + 1e-9], [45, 45])
    # β ≈ 1.7e-11 rad, so RF − 1 ≈ 2.5e-23: the trapezoid (RF = 1) is an exact oracle
    exp_n = dmd / 2 * (np.sin(i1) + np.sin(i2)) * np.cos(az)
    exp_v = dmd / 2 * (np.cos(i1) + np.cos(i2))
    assert b["north_m"][-1] == pytest.approx(exp_n, abs=1e-13)
    assert b["tvd_m"][-1] == pytest.approx(exp_v, abs=1e-13)


def test_public_helpers_guard_inputs() -> None:
    with pytest.raises(InputValidationError, match="beta_rad"):
        ratio_factor([np.nan])
    with pytest.raises(InputValidationError, match="beta_rad"):
        ratio_factor([np.pi])
    with pytest.raises(InputValidationError, match="beta_rad"):
        ratio_factor([-0.1])
    with pytest.raises(InputValidationError, match="lengths differ"):
        dogleg_angle([0.1], [0.1], [0.1, 0.2], [0.1])
    assert normalize_azimuth(-10.0).tolist() == [350.0]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_degenerate_course_raises_numerical_error() -> None:
    with pytest.raises(NumericalError, match="dls"):
        mc([0.0, 5e-324], [0, 10], [0, 0])


def test_atan2_dogleg_agrees_with_arccos_for_moderate_angles() -> None:
    rng = np.random.default_rng(12345)
    i1, i2 = np.radians(rng.uniform(5, 90, 500)), np.radians(rng.uniform(5, 90, 500))
    a1, a2 = np.radians(rng.uniform(0, 360, 500)), np.radians(rng.uniform(0, 360, 500))
    classic = np.arccos(
        np.clip(np.cos(i2 - i1) - np.sin(i1) * np.sin(i2) * (1 - np.cos(a2 - a1)), -1, 1)
    )
    assert np.allclose(dogleg_angle(i1, a1, i2, a2), classic, atol=1e-10)


def test_normalize_azimuth_edge() -> None:
    out = normalize_azimuth(np.array([-1e-17, 360.0, 720.5, -90.0]))
    assert out.tolist() == [0.0, 0.0, 0.5, 270.0]


# --- property tests -----------------------------------------------------------
angles_inc = st.floats(0.0, 170.0)
angles_azi = st.floats(-720.0, 720.0)


@st.composite
def surveys(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = draw(st.integers(2, 12))
    steps = draw(st.lists(st.floats(0.5, 200.0), min_size=n - 1, max_size=n - 1))
    md = np.concatenate(([0.0], np.cumsum(steps)))
    inc = np.array(draw(st.lists(angles_inc, min_size=n, max_size=n)))
    azi = np.array(draw(st.lists(angles_azi, min_size=n, max_size=n)))
    return md, inc, azi


def _ok(md: np.ndarray, inc: np.ndarray, azi: np.ndarray) -> bool:
    beta = dogleg_angle(
        np.radians(inc[:-1]), np.radians(azi[:-1]), np.radians(inc[1:]), np.radians(azi[1:])
    )
    return bool(np.all(beta < np.radians(170.0)))


@given(surveys())
def test_property_finite_and_course_length_bound(s: tuple[np.ndarray, ...]) -> None:
    md, inc, azi = s
    if not _ok(md, inc, azi):
        return
    r = mc(md, inc, azi)
    for k, v in r.values.items():
        assert np.all(np.isfinite(v)), k
    chord = np.sqrt(r["delta_north_m"] ** 2 + r["delta_east_m"] ** 2 + r["delta_tvd_m"] ** 2)
    assert np.all(chord <= np.diff(md) * (1 + 1e-12))  # chord never exceeds arc length
    assert np.all((r["closure_azimuth_deg"] >= 0) & (r["closure_azimuth_deg"] < 360))


@given(surveys(), st.floats(-360.0, 360.0))
def test_property_rotation(s: tuple[np.ndarray, ...], theta: float) -> None:
    md, inc, azi = s
    if not _ok(md, inc, azi):
        return
    a = mc(md, inc, azi)
    b = mc(md, inc, azi + theta)
    t = np.radians(theta)
    # rotating azimuths clockwise by θ rotates (E, N) clockwise by θ
    e_rot = a["east_m"] * np.cos(t) + a["north_m"] * np.sin(t)
    n_rot = -a["east_m"] * np.sin(t) + a["north_m"] * np.cos(t)
    scale = float(md[-1])
    assert np.allclose(b["east_m"], e_rot, atol=1e-9 * scale)
    assert np.allclose(b["north_m"], n_rot, atol=1e-9 * scale)
    assert np.allclose(b["tvd_m"], a["tvd_m"], atol=1e-9 * scale)
    assert np.allclose(b["dogleg_deg"], a["dogleg_deg"], atol=1e-9)


def _slerp_tangents(t1: np.ndarray, t2: np.ndarray, k: int) -> np.ndarray:
    """Independent oracle: tangents along the great-circle arc from t1 to t2."""
    om = np.arccos(np.clip(t1 @ t2, -1, 1))
    f = np.linspace(0, 1, k)
    if om < 1e-12:
        return np.tile(t1, (k, 1))
    return (np.sin((1 - f) * om)[:, None] * t1 + np.sin(f * om)[:, None] * t2) / np.sin(om)


@given(
    angles_inc,
    st.floats(0, 360),
    angles_inc,
    st.floats(0, 360),
    st.integers(3, 15),
    st.floats(10.0, 2000.0),
)
def test_property_subdivision_exact_for_arcs(
    i1: float, a1: float, i2: float, a2: float, k: int, length: float
) -> None:
    def tan(i: float, a: float) -> np.ndarray:
        i, a = np.radians(i), np.radians(a)
        return np.array([np.sin(i) * np.sin(a), np.sin(i) * np.cos(a), np.cos(i)])

    t1, t2 = tan(i1, a1), tan(i2, a2)
    if np.arccos(np.clip(t1 @ t2, -1, 1)) > np.radians(170.0):
        return
    ts = _slerp_tangents(t1, t2, k)
    # atan2, not arccos: arccos(t_z) loses precision near 0° inclination
    inc = np.degrees(np.arctan2(np.hypot(ts[:, 0], ts[:, 1]), ts[:, 2]))
    azi = np.degrees(np.arctan2(ts[:, 0], ts[:, 1]))
    md = np.linspace(0.0, length, k)
    coarse = mc([0.0, length], inc[[0, -1]], azi[[0, -1]])
    fine = mc(md, inc, azi)
    for key in ("north_m", "east_m", "tvd_m"):
        assert fine[key][-1] == pytest.approx(coarse[key][-1], abs=1e-9 * length)
