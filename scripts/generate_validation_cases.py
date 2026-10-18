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


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    well_path_cases()
    well_path_literature()
    petrophysics_cases()
    petrophysics_literature()
    print(f"wrote {len(list(OUT.glob('*.json')))} cases to {OUT}")
