"""End-to-end example: trajectory + petrophysics, each printed as an auditable record.

Usage:  python examples/end_to_end.py

All inputs below are SYNTHETIC illustrative values, not field data.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from georeservoir.engineering import petrophysics as pp
from georeservoir.engineering.well_path import minimum_curvature


def main() -> None:
    # 1) Build-and-hold trajectory (synthetic survey, MD in metres, true north)
    traj = minimum_curvature(
        md=[0, 500, 800, 1100, 1400, 2000],
        inclination_deg=[0, 0, 15, 30, 30, 30],
        azimuth_deg=[0, 0, 135, 135, 135, 135],
        length_unit="m",
        azimuth_reference="true",
        start_east=0.0,
        start_north=0.0,
        start_tvd=0.0,
    )
    print("=== Trajectory: final station ===")
    for k in ("md_m", "tvd_m", "north_m", "east_m", "horizontal_displacement_m"):
        print(f"{k:>28}: {traj[k][-1]:.3f} {traj.units[k]}")
    print(f"{'max DLS':>28}: {traj['dls_deg_per_30m'].max():.3f} deg/30m")

    # 2) Petrophysics on a synthetic 4-sample interval
    igr = pp.gamma_ray_index([25, 45, 80, 110], gr_min_api=20, gr_max_api=120, clip=True)
    vsh = pp.vsh_larionov_older(igr["igr"])
    phi = pp.density_porosity(
        [2.30, 2.35, 2.45, 2.55], rho_matrix_g_cc=2.65, rho_fluid_g_cc=1.0, clip=True
    )
    sw = pp.archie_water_saturation(
        phi["porosity"], [40.0, 18.0, 6.0, 2.5], rw_ohm_m=0.05, a=1.0, m=2.0, n=2.0, clip=True
    )
    print("\n=== Petrophysics ===")
    print("Vsh :", [round(float(x), 4) for x in vsh["vsh"]])
    print("PHID:", [round(float(x), 4) for x in phi["porosity"]])
    print("Sw  :", [round(float(x), 4) for x in sw["sw"]])

    print("\n=== CalculationRecord (Archie Sw) as JSON ===")
    print(sw.to_json(indent=2))


if __name__ == "__main__":
    main()
