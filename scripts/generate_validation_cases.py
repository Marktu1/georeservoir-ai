"""Generate tests/validation/cases/*.json from CLOSED-FORM oracles.

This script deliberately does NOT import ``georeservoir``: expected values come
from exact geometry or hand-checkable arithmetic of the published equations, so
the validation oracle is independent of the implementation.

Usage:  python scripts/generate_validation_cases.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "tests" / "validation" / "cases"

GEO_TOL = {
    "tol_abs": 1e-11,
    "tol_rel": 1e-13,
    "tolerance_justification": (
        "Closed-form oracle. Positions are O(1e3) m, so one float64 ulp is ~1e-13 m; "
        "cumulative sums over ≤10 courses accumulate ≤~1e-12 m. 1e-11 m absolute "
        "(+1e-13 relative) is ~10x that bound. For DLS (deg/30m, O(1)) the same "
        "numbers are ~1e-14 deg/30m, far inside the tolerance."
    ),
}
PET_TOL = {
    "tol_abs": 1e-14,
    "tol_rel": 1e-14,
    "tolerance_justification": (
        "Arithmetic on O(1) fractions; float64 rounding ~1e-16, a few operations "
        "-> ≤~1e-15. 1e-14 is ~10x that bound."
    ),
}
BASE = {
    "length_unit": "m",
    "azimuth_reference": "true",
    "start_east": 0.0,
    "start_north": 0.0,
    "start_tvd": 0.0,
}


def write(case: dict[str, Any]) -> None:
    (OUT / f"{case['id']}.json").write_text(json.dumps(case, indent=2) + "\n")


def well_path_cases() -> None:
    md = [0.0, 250.0, 500.0, 750.0, 1000.0]
    common = {"module": "well_path", "function": "well_path.minimum_curvature"}
    write(
        {
            "id": "VAL-WP-001",
            **common,
            "kind": "analytical",
            "description": "Vertical well: TVD = MD, zero horizontal displacement, zero dogleg.",
            "source": "Exact geometry (straight vertical line).",
            "source_status": "confirmed",
            "kwargs": {
                **BASE,
                "md": md,
                "inclination_deg": [0.0] * 5,
                "azimuth_deg": [0.0, 37.0, 123.0, 250.0, 359.0],
            },
            "expected": {
                "tvd_m": md,
                "north_m": [0.0] * 5,
                "east_m": [0.0] * 5,
                "horizontal_displacement_m": [0.0] * 5,
                "dogleg_deg": [0.0] * 4,
            },
            **GEO_TOL,
        }
    )
    inc, azi = 30.0, 60.0
    si, ci = math.sin(math.radians(inc)), math.cos(math.radians(inc))
    write(
        {
            "id": "VAL-WP-002",
            **common,
            "kind": "analytical",
            "description": "Straight inclined tangent (I=30°, A=60°): N = MD·sinI·cosA, "
            "E = MD·sinI·sinA, TVD = MD·cosI.",
            "source": "Exact trigonometry of a straight line.",
            "source_status": "confirmed",
            "kwargs": {**BASE, "md": md, "inclination_deg": [inc] * 5, "azimuth_deg": [azi] * 5},
            "expected": {
                "north_m": [m * si * math.cos(math.radians(azi)) for m in md],
                "east_m": [m * si * math.sin(math.radians(azi)) for m in md],
                "tvd_m": [m * ci for m in md],
            },
            **GEO_TOL,
        }
    )
    radius = 500.0
    arc = radius * math.pi / 2
    for cid, n in (("VAL-WP-003", 2), ("VAL-WP-004", 10)):
        mds = [arc * k / (n - 1) for k in range(n)]
        th = [x / radius for x in mds]
        extra = (
            " Subdivision: exactness for arcs means intermediate stations lie on the arc."
            if n > 2
            else ""
        )
        write(
            {
                "id": cid,
                **common,
                "kind": "analytical",
                "description": f"Circular build arc in a vertical plane, R = 500 m, I 0°→90° at "
                f"azimuth 0°, {n} stations. N = R(1−cosθ), TVD = R·sinθ, θ = MD/R; "
                f"DLS = 90°/L·30 m.{extra}",
                "source": "Exact circle geometry.",
                "source_status": "confirmed",
                "kwargs": {
                    **BASE,
                    "md": mds,
                    "inclination_deg": [math.degrees(t) for t in th],
                    "azimuth_deg": [0.0] * n,
                },
                "expected": {
                    "north_m": [radius * (1 - math.cos(t)) for t in th],
                    "tvd_m": [radius * math.sin(t) for t in th],
                    "east_m": [0.0] * n,
                    "dls_deg_per_30m": [90.0 / arc * 30.0] * (n - 1),
                },
                **GEO_TOL,
            }
        )
    write(
        {
            "id": "VAL-WP-L02",
            **common,
            "kind": "literature",
            "description": "ISCWSA test well #1 (published survey listing).",
            "source": "ISCWSA (Industry Steering Committee on Wellbore Survey Accuracy) "
            "published test wells (listing not obtained in this execution).",
            "source_status": "fonte por verificar",
            "kwargs": None,
            "expected": None,
            "tol_abs": None,
            "tol_rel": None,
            "tolerance_justification": "To be set from the precision of the published listing.",
        }
    )


def well_path_literature() -> None:
    """Published build example (values typed from the source, not computed)."""
    ft = 0.3048
    half_ulp_ft = 0.005  # published to 0.01 ft
    write(
        {
            "id": "VAL-WP-L01",
            "module": "well_path",
            "function": "well_path.minimum_curvature",
            "kind": "literature",
            "description": (
                "Build section due North at 3°/100 ft, surveys every 100 ft, 0° at MD 0 to "
                "60° at MD 2,000 ft. Published minimum-curvature result at 2,000 ft: "
                "TVD = 1,653.99 ft, North = 954.93 ft (compared here in metres)."
            ),
            "source": (
                "Bourgoyne, A.T., Millheim, K.K., Chenevert, M.E. & Young, F.S. (1991), Applied "
                "Drilling Engineering, SPE Textbook Series Vol. 2 — as tabulated in Amorin, R. & "
                "Broni-Bediako, E. (2010), Application of Minimum Curvature Method to Wellpath "
                "Calculations, Proc. 1st Biennial UMaT Int. Conf. on Mining & Mineral "
                "Processing, Tarkwa, Ghana, pp. 524-541 (Table B / Table 1.5)"
            ),
            "source_status": "confirmed",
            "source_check": (
                "Values read from the Amorin & Broni-Bediako (2010) PDF (UMaT repository) on "
                "2026-10-18; the Bourgoyne original was not consulted directly."
            ),
            "kwargs": {
                **BASE,
                "length_unit": "ft",
                "md": [100.0 * k for k in range(21)],
                "inclination_deg": [3.0 * k for k in range(21)],
                "azimuth_deg": [0.0] * 21,
            },
            "expected_index": -1,
            "expected": {"tvd_m": [1653.99 * ft], "north_m": [954.93 * ft], "east_m": [0.0]},
            "tol_abs": half_ulp_ft * ft,
            "tol_rel": 0.0,
            "tolerance_justification": (
                "Published values are rounded to 0.01 ft, so the reference is only known to "
                "±0.005 ft (= 0.001524 m). No further allowance."
            ),
        }
    )


def petrophysics_cases() -> None:
    src = "Hand-checkable evaluation of the published equation (verifies transcription)."

    def pc(
        cid: str, fn: str, desc: str, kwargs: dict[str, Any], expected: dict[str, list[float]]
    ) -> None:
        write(
            {
                "id": cid,
                "module": "petrophysics",
                "function": fn,
                "kind": "spec_conformance",
                "description": desc,
                "source": src,
                "source_status": "confirmed",
                "kwargs": kwargs,
                "expected": expected,
                **PET_TOL,
            }
        )

    pc(
        "VAL-PP-001",
        "petrophysics.gamma_ray_index",
        "IGR at GRmin, midpoint and GRmax.",
        {"gr_api": [20.0, 70.0, 120.0], "gr_min_api": 20.0, "gr_max_api": 120.0, "clip": False},
        {"igr": [0.0, 0.5, 1.0]},
    )
    pc(
        "VAL-PP-002",
        "petrophysics.vsh_steiber",
        "Steiber at IGR = 0, 0.5, 1 → 0, 0.25, 1.",
        {"igr": [0.0, 0.5, 1.0]},
        {"vsh": [0.0, 0.25, 1.0]},
    )
    pc(
        "VAL-PP-003",
        "petrophysics.vsh_larionov_older",
        "Larionov older at IGR = 0, 0.5, 1 → 0, 0.33, 0.99.",
        {"igr": [0.0, 0.5, 1.0]},
        {"vsh": [0.0, 0.33, 0.99]},
    )
    pc(
        "VAL-PP-004",
        "petrophysics.vsh_larionov_tertiary",
        "Larionov Tertiary at IGR = 0.5 → 0.083·(2^1.85 − 1).",
        {"igr": [0.5]},
        {"vsh": [0.083 * (2**1.85 - 1)]},
    )
    pc(
        "VAL-PP-005",
        "petrophysics.vsh_clavier",
        "Clavier at IGR = 0.5 → 1.7 − √1.94.",
        {"igr": [0.5]},
        {"vsh": [1.7 - math.sqrt(1.94)]},
    )
    pc(
        "VAL-PP-006",
        "petrophysics.density_porosity",
        "ρb = 2.40, ρma = 2.65 (quartz), ρfl = 1.0 → 0.25/1.65.",
        {"rho_bulk_g_cc": [2.40], "rho_matrix_g_cc": 2.65, "rho_fluid_g_cc": 1.0, "clip": False},
        {"porosity": [0.25 / 1.65]},
    )
    pc(
        "VAL-PP-007",
        "petrophysics.sonic_porosity_wyllie",
        "Δt = 80, Δtma = 55.5, Δtfl = 189 µs/ft → 24.5/133.5.",
        {
            "dt_us_per_ft": [80.0],
            "dt_matrix_us_per_ft": 55.5,
            "dt_fluid_us_per_ft": 189.0,
            "clip": False,
        },
        {"porosity": [24.5 / 133.5]},
    )
    pc(
        "VAL-PP-008",
        "petrophysics.archie_water_saturation",
        "φ = 0.20, Rt = 20, Rw = 0.05 ohm·m, a = 1, m = n = 2 → Sw = √(0.05/(0.04·20)) = 0.25.",
        {
            "porosity": [0.2],
            "rt_ohm_m": [20.0],
            "rw_ohm_m": 0.05,
            "a": 1.0,
            "m": 2.0,
            "n": 2.0,
            "clip": False,
        },
        {"sw": [0.25]},
    )
    write(
        {
            "id": "VAL-PP-L02",
            "module": "petrophysics",
            "function": "petrophysics.archie_water_saturation",
            "kind": "literature",
            "description": "Published worked example of an Archie Sw computation.",
            "source": "Candidate: Asquith & Krygowski (2004), Basic Well Log Analysis, AAPG — "
            "exercise values not verified in this execution.",
            "source_status": "fonte por verificar",
            "kwargs": None,
            "expected": None,
            "tol_abs": None,
            "tol_rel": None,
            "tolerance_justification": "To be set from the rounding of the published example.",
        }
    )


def petrophysics_literature() -> None:
    """Published Archie example (values typed from the source, not computed)."""
    # Zone: (Rt ohm.m, porosity %, printed Sw)
    zones = {
        "A": (39.0, 24.0, 0.18),
        "B": (31.0, 10.0, 0.45),
        "C": (36.0, 20.0, 0.22),
        "D": (30.0, 20.0, 0.25),
        "E": (19.0, 22.0, 0.28),
        "F": (9.0, 18.0, 0.49),
        "G": (2.0, 19.0, 1.00),
        "H": (1.5, 23.0, 0.97),
        "I": (4.0, 12.0, 1.07),
        "J": (7.0, 10.0, 0.95),
    }
    write(
        {
            "id": "VAL-PP-L01",
            "module": "petrophysics",
            "function": "petrophysics.archie_water_saturation",
            "kind": "literature",
            "description": (
                "Archie Sw for 10 zones (A–J) of the hypothetical 'Rottweiler Sandstone': "
                "a = 1, m = 1.8, n = 2, Rw = 0.10 ohm·m. Compared with sw_raw (no clipping): "
                "zone I is published as 1.07 (> 1)."
            ),
            "source": (
                "Kansas Geological Survey, PfEFFER Concepts — 'Archie Computational Equations' "
                "(kgs.ku.edu/software/PfEFFER-java/HELP/PfEFFER/Pfeffer-theory2.html), page "
                "updated July 2010"
            ),
            "source_status": "confirmed",
            "source_check": "Table values read from the KGS page on 2026-10-18.",
            "kwargs": {
                "porosity": [v[1] / 100.0 for v in zones.values()],
                "rt_ohm_m": [v[0] for v in zones.values()],
                "rw_ohm_m": 0.10,
                "a": 1.0,
                "m": 1.8,
                "n": 2.0,
                "clip": False,
            },
            "expected": {"sw_raw": [v[2] for v in zones.values()]},
            "tol_abs": 0.005,
            "tol_rel": 0.0,
            "tolerance_justification": (
                "Published Sw is rounded to 0.01, so the reference is only known to ±0.005."
            ),
        }
    )


# SPEE REP #6 Table 1 (values typed from the source; percent, 6 decimals, per year)
SPEE_NOMINAL_PCT = [
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    20,
    30,
    40,
    50,
    60,
    70,
    80,
    90,
    100,
    200,
    300,
    400,
    500,
    600,
    700,
    800,
    900,
    1000,
]
SPEE_SECANT_PCT = {
    0.0: [
        0.995017,
        1.980133,
        2.955447,
        3.921056,
        4.877058,
        5.823547,
        6.760618,
        7.688365,
        8.606881,
        9.516258,
        18.126925,
        25.918178,
        32.967995,
        39.346934,
        45.118836,
        50.341470,
        55.067104,
        59.343034,
        63.212056,
        86.466472,
        95.021293,
        98.168436,
        99.326205,
        99.752125,
        99.908812,
        99.966454,
        99.987659,
        99.995460,
    ],
    0.5: [
        0.992550,
        1.970395,
        2.933825,
        3.883122,
        4.818560,
        5.740409,
        6.648930,
        7.544379,
        8.427005,
        9.297052,
        17.355372,
        24.385633,
        30.555556,
        36.000000,
        40.828402,
        45.130316,
        48.979592,
        52.437574,
        55.555556,
        75.000000,
        84.000000,
        88.888889,
        91.836735,
        93.750000,
        95.061728,
        96.000000,
        96.694215,
        97.222222,
    ],
    1.0: [
        0.990099,
        1.960784,
        2.912621,
        3.846154,
        4.761905,
        5.660377,
        6.542056,
        7.407407,
        8.256881,
        9.090909,
        16.666667,
        23.076923,
        28.571429,
        33.333333,
        37.500000,
        41.176471,
        44.444444,
        47.368421,
        50.000000,
        66.666667,
        75.000000,
        80.000000,
        83.333333,
        85.714286,
        87.500000,
        88.888889,
        90.000000,
        90.909091,
    ],
    1.5: [
        0.987664,
        1.951298,
        2.891822,
        3.810111,
        4.706995,
        5.583260,
        6.439655,
        7.276891,
        8.095645,
        8.896561,
        16.046701,
        21.941297,
        26.899557,
        31.138792,
        34.812509,
        38.032483,
        40.882207,
        43.425409,
        45.711648,
        60.314974,
        67.905924,
        72.672412,
        75.990264,
        78.455653,
        80.372359,
        81.912810,
        83.182762,
        84.250987,
    ],
    2.0: [
        0.985246,
        1.941932,
        2.871414,
        3.774955,
        4.653741,
        5.508882,
        6.341419,
        7.152331,
        7.942538,
        8.712907,
        15.484575,
        20.943058,
        25.464401,
        29.289322,
        32.580014,
        35.450278,
        37.982633,
        40.238570,
        42.264973,
        55.278640,
        62.203553,
        66.666667,
        69.848866,
        72.264990,
        74.180111,
        75.746437,
        77.058427,
        78.178211,
    ],
}
SPEE_SRC = (
    "SPEE Recommended Evaluation Practice #6, Definition of Decline Curve Parameters, "
    "Society of Petroleum Evaluation Engineers (copyright 2000, v1.0 adopted 2002), Table 1"
)
SPEE_TOL = {
    "tol_abs": 5e-9,
    "tol_rel": 0.0,
    "tolerance_justification": (
        "Table 1 prints percentages to 6 decimals, i.e. fractions known to ±5e-9."
    ),
}


def dca_cases() -> None:
    from scipy.integrate import quad

    def rate(t: float, qi: float, di: float, b: float) -> float:
        # independent oracle: textbook forms, not the library's log1p formulation
        return qi * math.exp(-di * t) if b == 0 else qi * (1 + b * di * t) ** (-1 / b)

    ts = [0.0, 6.0, 12.0, 24.0, 60.0]
    for cid, b in (
        ("VAL-DCA-001", 0.0),
        ("VAL-DCA-002", 0.5),
        ("VAL-DCA-003", 1.0),
        ("VAL-DCA-004", 1.6),
    ):
        cum = [quad(rate, 0, t, args=(1000.0, 0.1, b), epsabs=1e-12, epsrel=1e-13)[0] for t in ts]
        write(
            {
                "id": cid,
                "module": "dca",
                "function": "dca.arps_cumulative",
                "kind": "analytical",
                "description": f"Arps cumulative (qi = 1000, Di = 0.1/month, b = {b}) against "
                "adaptive numerical quadrature of the textbook rate form q = qi(1+bDit)^(-1/b).",
                "source": "Independent numerical integration (scipy.integrate.quad).",
                "source_status": "confirmed",
                "kwargs": {
                    "t": ts,
                    "qi": 1000.0,
                    "di": 0.1,
                    "b": b,
                    "time_unit": "month",
                    "d_terminal": None,
                },
                "expected": {"np": cum},
                "tol_abs": 1e-7,
                "tol_rel": 1e-11,
                "tolerance_justification": "quad requested to 1e-12 abs / 1e-13 rel; cumulatives "
                "are O(1e4), so float64 evaluation error is ~1e-12 relative. 1e-11 rel is ~10x.",
            }
        )
    d = [v / 100 for v in SPEE_NOMINAL_PCT]
    for b, eff in SPEE_SECANT_PCT.items():
        tag = str(b).replace(".", "")
        write(
            {
                "id": f"VAL-DCA-L01-b{tag}",
                "module": "dca",
                "function": "dca.nominal_to_effective_decline",
                "kind": "literature",
                "description": f"Nominal → effective decline, b = {b} "
                f"({'tangent = exponential' if b == 0 else 'secant'}), nominal 1 %–1000 %/yr.",
                "source": SPEE_SRC,
                "source_status": "confirmed",
                "source_check": "Table read from the SPEE REP #6 PDF on 2026-10-18.",
                "kwargs": {"d_nominal": d, "b": b},
                "expected": {"d_effective": [v / 100 for v in eff]},
                **SPEE_TOL,
            }
        )
        write(
            {
                "id": f"VAL-DCA-L02-b{tag}",
                "module": "dca",
                "function": "dca.arps_rate",
                "kind": "literature",
                "description": f"Arps rate after one year, b = {b}: per SPEE REP #6 "
                "the secant effective decline is 1 − q(1 yr)/qi, so q(1 yr) with qi = 1 "
                "must equal 1 − De(Table 1).",
                "source": SPEE_SRC,
                "source_status": "confirmed",
                "source_check": "Table read from the SPEE REP #6 PDF on 2026-10-18.",
                "kwargs": None,
                "expected": None,
                "per_row": [
                    {
                        "kwargs": {
                            "t": [1.0],
                            "qi": 1.0,
                            "di": dn,
                            "b": b,
                            "time_unit": "year",
                            "d_terminal": None,
                        },
                        "expected": {"q": [1 - v / 100]},
                    }
                    for dn, v in zip(d, eff, strict=False)
                ],
                **SPEE_TOL,
            }
        )


MOSUL_SRC = (
    "Production Engineering II lecture notes, 'IPR', Petroleum Engineering Department, "
    "University of Mosul (2017; uomosul.edu.iq, Lecture 4), citing Vogel (1968) and Beggs "
    "(1991) — published teaching material, not a peer-reviewed source"
)


def nodal_cases() -> None:
    # analytical: linear IPR x linear TPR -> closed-form intersection
    pr, j, a, c = 3000.0, 0.5, 1200.0, 0.8  # TPR: pwf = a + c q
    q_star = (pr - a) / (1 / j + c)
    write(
        {
            "id": "VAL-ND-001",
            "module": "nodal",
            "function": "nodal.nodal_solve_linear",
            "kind": "analytical",
            "description": "Linear IPR (p̄r = 3000, J = 0.5) and straight-line TPR pwf = 1200 + "
            "0.8q: unique stable intersection q* = (p̄r − a)/(1/J + c).",
            "source": "Exact algebra.",
            "source_status": "confirmed",
            "kwargs": {
                "p_res": pr,
                "j": j,
                "tpr_q": [0.0, 500.0, 1000.0, 1500.0],
                "tpr_pwf": [a + c * q for q in (0.0, 500.0, 1000.0, 1500.0)],
            },
            "expected": {"q_op": [q_star], "pwf_op": [a + c * q_star], "stable": [1.0]},
            "tol_abs": 1e-7,
            "tol_rel": 1e-12,
            "tolerance_justification": "Brent xtol = 1e-10 on O(1e3) rates; PCHIP reproduces "
            "collinear data exactly up to rounding.",
        }
    )
    common = {
        "module": "nodal",
        "kind": "literature",
        "source": MOSUL_SRC,
        "source_status": "confirmed",
        "source_check": "Tables read from the lecture PDF on 2026-10-18.",
    }
    write(
        {
            "id": "VAL-ND-L01",
            **common,
            "function": "nodal.ipr_vogel",
            "description": "Problem 1-3: saturated well, p̄r = 2500 psig, test 350 STB/d at 2000 "
            "psig. Published Vogel IPR table (q at pwf = 2200, 1500, 1000, 500, 0); the table "
            "uses qmax = 1067.1 (its value at pwf = 0). The text's '(Qo)max = 1076.1' is a "
            "transposition typo and is not used.",
            "kwargs": {
                "pwf": [2500.0, 2200.0, 1500.0, 1000.0, 500.0, 0.0],
                "p_res": 2500.0,
                "q_max": 1067.1,
                "pressure_unit": "psi",
            },
            "expected": {"q": [0.0, 218.2, 631.7, 845.1, 990.3, 1067.1]},
            "tol_abs": 0.05,
            "tol_rel": 0.0,
            "tolerance_justification": "Published to 0.1 STB/d: reference known to ±0.05.",
        }
    )
    write(
        {
            "id": "VAL-ND-L01b",
            **common,
            "function": "nodal.vogel_qmax_from_test",
            "description": "Problem 1-3: Vogel qmax from the test (350 STB/d at 2000 psig, "
            "p̄r = 2500) must round to the table's 1067.1.",
            "kwargs": {
                "p_res": 2500.0,
                "q_test": 350.0,
                "pwf_test": 2000.0,
                "pressure_unit": "psi",
            },
            "expected": {"q_max": [1067.1]},
            "tol_abs": 0.05,
            "tol_rel": 0.0,
            "tolerance_justification": "Published to 0.1 STB/d: reference known to ±0.05.",
        }
    )
    write(
        {
            "id": "VAL-ND-L02",
            **common,
            "function": "nodal.ipr_composite",
            "description": "Problem 1-4: undersaturated, pb = 2130, p̄r = 3000 psig, J = 0.5 "
            "STB/d/psi. Published composite IPR table and qb = 435 STB/d.",
            "kwargs": {
                "pwf": [3000.0, 2800.0, 2600.0, 2130.0, 1500.0, 1000.0, 500.0, 0.0],
                "p_res": 3000.0,
                "p_bubble": 2130.0,
                "j": 0.5,
                "pressure_unit": "psi",
            },
            "expected": {
                "q": [0.0, 100.0, 200.0, 435.0, 709.0, 867.0, 973.0, 1027.0],
                "q_b": [435.0],
            },
            "tol_abs": 0.5,
            "tol_rel": 0.0,
            "tolerance_justification": "Published to 1 STB/d: reference known to ±0.5.",
        }
    )
    write(
        {
            "id": "VAL-ND-L03",
            **common,
            "function": "nodal.composite_j_from_test",
            "description": "Problem 1-5: retest below pb (630.7 STB/d at 1700 psig, pb = 2130, "
            "p̄r = 3000) gives J = 0.5 STB/d/psi.",
            "kwargs": {
                "p_res": 3000.0,
                "p_bubble": 2130.0,
                "q_test": 630.7,
                "pwf_test": 1700.0,
                "pressure_unit": "psi",
            },
            "expected": {"j": [0.5]},
            "tol_abs": 0.05,
            "tol_rel": 0.0,
            "tolerance_justification": "Published to 0.1 STB/d/psi: reference known to ±0.05.",
        }
    )


def bourdet_cases() -> None:
    common = {
        "module": "bourdet",
        "function": "bourdet.bourdet_derivative",
        "kind": "analytical",
        "source_status": "confirmed",
    }
    t = [0.01, 0.013, 0.02, 0.031, 0.05, 0.09, 0.2, 0.35, 0.7, 1.5, 3.0, 7.0, 15.0]
    m, c0 = 37.5, 120.0
    write(
        {
            "id": "VAL-BD-001",
            **common,
            "description": "Infinite-acting radial flow shape Δp = m·ln t + c (m = 37.5 psi) on "
            "irregular times, L = 0.2: the derivative equals m at every point, central and "
            "one-sided.",
            "source": "Exact: every weighted difference of a linear function of X = ln t is its "
            "slope.",
            "kwargs": {
                "dt": t,
                "dp": [m * math.log(x) + c0 for x in t],
                "window_ln": 0.2,
                "sigma_p": 0.0,
                "pressure_unit": "psi",
            },
            "expected": {"derivative": [m] * len(t)},
            "tol_abs": 1e-12,
            "tol_rel": 0.0,
            "tolerance_justification": "Differences of O(1e2) psi over ΔX ≥ 0.2 divided by "
            "O(0.1–1): rounding ~1e-13 psi. 1e-12 is ~10x that bound.",
        }
    )
    h = 0.3
    xs = [math.log(0.01) + h * k for k in range(25)]
    ts = [math.exp(x) for x in xs]
    exp_d = (
        [ts[0] * (math.exp(h) - 1) / h]
        + [x * math.sinh(h) / h for x in ts[1:-1]]
        + [ts[-1] * (1 - math.exp(-h)) / h]
    )
    write(
        {
            "id": "VAL-BD-002",
            **common,
            "description": "Wellbore-storage shape Δp = t with uniform log spacing h = L = 0.3: "
            "interior derivative = Δp·sinh(L)/L (the exact discrete Bourdet result, smoothing "
            "bias ≈ L²/6), first point forward Δp(e^L − 1)/L, last point backward "
            "Δp(1 − e^(−L))/L.",
            "source": "Exact discrete algebra of the Bourdet formula on exponential data.",
            "kwargs": {"dt": ts, "dp": ts, "window_ln": h, "sigma_p": 0.0, "pressure_unit": "psi"},
            "expected": {"derivative": exp_d},
            "tol_abs": 0.0,
            "tol_rel": 1e-12,
            "tolerance_justification": "Values span 1e-2 to ~1e1; float64 evaluation of "
            "exp/sinh and three-point sums gives ≤~1e-13 relative after the 1/L division. "
            "1e-12 relative is ~10x that bound.",
        }
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    well_path_cases()
    well_path_literature()
    petrophysics_cases()
    petrophysics_literature()
    dca_cases()
    nodal_cases()
    bourdet_cases()
    print(f"wrote {len(list(OUT.glob('*.json')))} cases to {OUT}")
