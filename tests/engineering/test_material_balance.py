"""Unit and property tests for Havlena–Odeh material balance (spec §5.6)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from georeservoir.common.exceptions import (
    IdentifiabilityError,
    InputValidationError,
    PhysicalConsistencyError,
)
from georeservoir.engineering import material_balance as mb

PVT: dict[str, Any] = {
    "bo_rb_stb": [1.30, 1.29, 1.28, 1.27, 1.26],
    "bg_rb_scf": [0.00090, 0.00095, 0.00100, 0.00106, 0.00113],
    "rs_scf_stb": [600.0, 570.0, 540.0, 510.0, 480.0],
    "pi_psia": 3330.0,
    "boi_rb_stb": 1.31,
    "bgi_rb_scf": 0.00087,
    "rsi_scf_stb": 630.0,
    "cw_per_psi": 3e-6,
    "cf_per_psi": 4e-6,
    "swi": 0.2,
}
P = [3300.0, 3150.0, 3000.0, 2850.0, 2700.0]


def terms(m: float) -> Any:
    return mb.expansion_terms(P, **{**PVT, "m": m})


def test_underground_withdrawal_formula() -> None:
    r = mb.underground_withdrawal(
        [1e5],
        [800.0],
        [2e3],
        bo_rb_stb=[1.25],
        bg_rb_scf=[0.001],
        rs_scf_stb=[500.0],
        bw_rb_stb=[1.02],
    )
    assert r["f_rb"][0] == pytest.approx(1e5 * (1.25 + 300.0 * 0.001) + 2e3 * 1.02)


def test_expansion_terms_zero_at_initial_conditions() -> None:
    e = mb.expansion_terms(
        [3330.0],
        bo_rb_stb=[1.31],
        bg_rb_scf=[0.00087],
        rs_scf_stb=[630.0],
        **{k: v for k, v in PVT.items() if k not in ("bo_rb_stb", "bg_rb_scf", "rs_scf_stb")},
        m=0.3,
    )
    assert e["eo"][0] == 0.0 and e["eg"][0] == 0.0 and e["efw"][0] == 0.0


@given(st.floats(1e5, 1e9), st.floats(0.0, 3.0), st.integers(0, 2**31 - 1))
def test_property_recovers_n_and_m_with_noise(n_true: float, m_true: float, seed: int) -> None:
    e = terms(m_true)
    f = n_true * (e["eo"] + m_true * e["eg"] + e["efw"])
    assert mb.fit_known_m(f, e["eo"], e["eg"], e["efw"], m=m_true, we_rb=None)[
        "n_stb"
    ] == pytest.approx(n_true, rel=1e-10)
    rng = np.random.default_rng(seed)
    noisy = f * (1 + rng.normal(0, 1e-3, f.size))  # 0.1 % multiplicative noise
    r = mb.fit_known_m(noisy, e["eo"], e["eg"], e["efw"], m=m_true, we_rb=None)
    # 5 points, dof = 4: s.e.-based bounds are unreliable; the noise bounds |ΔN/N| < 1 %
    assert abs(r["n_stb"] / n_true - 1.0) < 1e-2
    assert r["n_se_stb"] > 0.0


def test_gas_cap_fit_recovers_both() -> None:
    e = terms(0.0)
    f = 3e7 * (e["eo"] + 0.7 * e["eg"])
    r = mb.fit_gas_cap_unknown_m(f, e["eo"], e["eg"], we_rb=None)
    assert r["n_stb"] == pytest.approx(3e7, rel=1e-9) and r["m"] == pytest.approx(0.7, rel=1e-8)
    assert r["r2"] == pytest.approx(1.0)


def test_identifiability_guards() -> None:
    e = terms(0.0)
    with pytest.raises(IdentifiabilityError, match="at least 2"):
        mb.fit_no_cap_no_aquifer([1.0], [0.1], [0.0], we_rb=None)
    with pytest.raises(IdentifiabilityError, match="not identifiable"):
        mb.fit_no_cap_no_aquifer([0.0, 0.0], [0.0, 0.0], [0.0, 0.0], we_rb=None)
    with pytest.raises(IdentifiabilityError, match="at least 3"):
        mb.fit_gas_cap_unknown_m([1.0, 2.0], [0.1, 0.2], [0.1, 0.2], we_rb=None)
    # Eg/Eo constant → N and m cannot be separated
    with pytest.raises(IdentifiabilityError, match="nearly"):
        mb.fit_gas_cap_unknown_m([1.0, 2.0, 3.0], [0.1, 0.2, 0.3], [0.2, 0.4, 0.6], we_rb=None)
    with pytest.raises(InputValidationError, match=r"eo\[0\]"):
        mb.fit_gas_cap_unknown_m(e["eo"], np.zeros(5), e["eg"], we_rb=None)


def test_physical_consistency() -> None:
    with pytest.raises(PhysicalConsistencyError, match="p <= pi"):
        mb.expansion_terms(
            [3400.0],
            **{**PVT, "bo_rb_stb": [1.3], "bg_rb_scf": [0.001], "rs_scf_stb": [600.0], "m": 0.0},
        )
    e = terms(0.0)
    with pytest.raises(PhysicalConsistencyError, match="not positive"):
        mb.fit_gas_cap_unknown_m(-1e6 * e["eo"], e["eo"], e["eg"], we_rb=None)


def test_negative_m_warns() -> None:
    e = terms(0.0)
    f = 3e7 * (e["eo"] - 0.2 * e["eg"])
    r = mb.fit_gas_cap_unknown_m(f, e["eo"], e["eg"], we_rb=None)
    assert {w.code for w in r.warnings} == {"NEGATIVE_M"}


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"swi": 1.0}, "swi"),
        ({"m": -0.1}, "m: received"),
        ({"cw_per_psi": -1e-6}, "cw"),
        ({"pi_psia": 0.0}, "pi_psia"),
    ],
)
def test_invalid_scalars(kw: dict[str, Any], match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        mb.expansion_terms(P, **{**PVT, "m": 0.0, **kw})


def test_invalid_we_and_m() -> None:
    e = terms(0.0)
    with pytest.raises(InputValidationError, match="we_rb"):
        mb.fit_no_cap_no_aquifer(e["eo"], e["eo"], e["efw"], we_rb=[1.0])
    with pytest.raises(InputValidationError, match="m: received"):
        mb.fit_known_m(e["eo"], e["eo"], e["eg"], e["efw"], m=-1.0, we_rb=None)
    with pytest.raises(InputValidationError, match=r"np_stb\[0\]"):
        mb.underground_withdrawal(
            [-1.0],
            [0.0],
            [0.0],
            bo_rb_stb=[1.2],
            bg_rb_scf=[0.001],
            rs_scf_stb=[0.0],
            bw_rb_stb=[1.0],
        )
