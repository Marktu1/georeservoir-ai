"""Tests for the common layer: exceptions, units, validation and CalculationRecord."""

from __future__ import annotations

import json

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from georeservoir import __version__
from georeservoir.common import units
from georeservoir.common.exceptions import (
    GeoReservoirError,
    IdentifiabilityError,
    InputValidationError,
    NumericalError,
    PhysicalConsistencyError,
)
from georeservoir.common.record import CalcWarning, array_digest, make_record
from georeservoir.common.validation import (
    as_1d_array,
    check_in_closed_range,
    check_positive_scalar,
    check_same_length,
    check_strictly_increasing,
    require_finite_scalar,
)

finite = st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False)


# --- exceptions ---------------------------------------------------------------
@pytest.mark.parametrize(
    "exc",
    [InputValidationError, PhysicalConsistencyError, NumericalError, IdentifiabilityError],
)
def test_exception_hierarchy(exc: type[Exception]) -> None:
    assert issubclass(exc, GeoReservoirError)


# --- units --------------------------------------------------------------------
def test_exact_factors() -> None:
    assert units.FT_TO_M == 0.3048
    assert units.length_to_si(1000.0, "ft") == pytest.approx(304.8, abs=1e-12)
    # 1 psi = 6894.757293168361 Pa (NIST SP 811 lists 6.894 757 E+03)
    assert pytest.approx(6894.757293168, rel=1e-12) == units.PSI_TO_PA
    assert units.pressure_to_si(1.0, "bar") == 1e5


@given(finite, st.sampled_from(["m", "ft"]))
def test_length_round_trip(x: float, u: units.LengthUnit) -> None:
    assert units.length_from_si(units.length_to_si(x, u), u) == pytest.approx(x, rel=1e-15)


@given(finite, st.sampled_from(["Pa", "kPa", "MPa", "psi", "bar"]))
def test_pressure_round_trip(x: float, u: units.PressureUnit) -> None:
    assert units.pressure_from_si(units.pressure_to_si(x, u), u) == pytest.approx(
        x, rel=1e-14, abs=1e-300
    )


def test_unknown_unit_rejected() -> None:
    with pytest.raises(InputValidationError, match="length unit"):
        units.length_to_si(1.0, "yd")  # type: ignore[arg-type]
    with pytest.raises(InputValidationError, match="pressure unit"):
        units.pressure_from_si(1.0, "atm")  # type: ignore[arg-type]
    with pytest.raises(InputValidationError, match="length unit"):
        units.length_to_si(1.0, ["m"])  # type: ignore[arg-type]


# --- validation ---------------------------------------------------------------
def test_as_1d_array_copies_and_promotes() -> None:
    src = np.array([1.0, 2.0])
    out = as_1d_array("x", src)
    out[0] = 99.0
    assert src[0] == 1.0
    assert as_1d_array("x", 3.0).shape == (1,)


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ([[1.0, 2.0]], "1-D"),
        ([1.0, np.nan], r"x\[1\]"),
        ([np.inf], "finite"),
        ("abc", "real number"),
        ([], "at least 1"),
    ],
)
def test_as_1d_array_rejects(value: object, match: str) -> None:
    with pytest.raises(InputValidationError, match=match):
        as_1d_array("x", value)  # type: ignore[arg-type]


def test_scalar_checks() -> None:
    assert require_finite_scalar("a", 2) == 2.0
    with pytest.raises(InputValidationError):
        require_finite_scalar("a", float("nan"))
    with pytest.raises(InputValidationError):
        require_finite_scalar("a", "x")  # type: ignore[arg-type]
    with pytest.raises(InputValidationError, match="> 0"):
        check_positive_scalar("a", 0.0)


def test_range_and_order_checks() -> None:
    a = np.array([0.0, 1.0, 1.0])
    with pytest.raises(InputValidationError, match=r"md\[2\]"):
        check_strictly_increasing("md", a)
    with pytest.raises(InputValidationError, match=r"inc\[1\]"):
        check_in_closed_range("inc", np.array([0.0, 181.0]), 0.0, 180.0)
    with pytest.raises(InputValidationError, match="lengths differ"):
        check_same_length(a=np.zeros(2), b=np.zeros(3))


# --- CalculationRecord --------------------------------------------------------
def _rec(x: list[float]) -> object:
    arr = np.array(x)
    return make_record(
        method="test.method",
        method_reference="ref",
        maturity="M1",
        values={"y": arr * 2, "n": 3},
        units={"y": "m", "n": "count"},
        scalar_inputs={"k": 1.5, "unit": "m"},
        array_inputs={"x": arr},
        assumptions=("A-001",),
        warnings=(CalcWarning("W", "msg", (1,)),),
    )


def test_record_is_deterministic_and_immutable() -> None:
    r1, r2 = _rec([1.0, 2.0]), _rec([1.0, 2.0])
    assert r1.inputs_hash == r2.inputs_hash  # type: ignore[attr-defined]
    assert r1.to_json() == r2.to_json()  # type: ignore[attr-defined]
    assert _rec([1.0, 2.0000001]).inputs_hash != r1.inputs_hash  # type: ignore[attr-defined]
    y = r1["y"]  # type: ignore[index]
    with pytest.raises(ValueError, match="read-only"):
        y[0] = 0.0
    with pytest.raises(AttributeError):
        r1.method = "x"  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        r1.values["z"] = 1  # type: ignore[attr-defined]


def test_record_json_contents() -> None:
    d = json.loads(_rec([1.0, 2.0]).to_json())  # type: ignore[attr-defined]
    assert d["values"] == {"n": 3, "y": [2.0, 4.0]}
    assert d["library_version"] == __version__
    assert d["inputs"]["x"] == array_digest(np.array([1.0, 2.0]))
    assert d["warnings"] == [{"code": "W", "message": "msg", "indices": [1]}]
    assert d["assumptions"] == ["A-001"]


def test_record_rejects_inconsistent_maps() -> None:
    with pytest.raises(InputValidationError, match="values/units"):
        make_record(
            method="m",
            method_reference="r",
            maturity="M1",
            values={"a": 1.0},
            units={"b": "m"},
            scalar_inputs={},
            array_inputs={},
        )
    with pytest.raises(InputValidationError, match="used twice"):
        make_record(
            method="m",
            method_reference="r",
            maturity="M1",
            values={},
            units={},
            scalar_inputs={"x": 1.0},
            array_inputs={"x": np.zeros(1)},
        )
