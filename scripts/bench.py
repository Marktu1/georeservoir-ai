"""Reference timings for realistic sizes. Writes docs/validation/bench.md.

Usage:  python scripts/bench.py
Synthetic inputs (seed 20261018); timings are machine-dependent references only.
"""

from __future__ import annotations

import platform
import sys
import timeit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from georeservoir.engineering import petrophysics as pp  # noqa: E402
from georeservoir.engineering.well_path import minimum_curvature  # noqa: E402


def main() -> None:
    rng = np.random.default_rng(20261018)
    n_s, n_l = 10_000, 100_000
    md = np.linspace(0.0, 6000.0, n_s)
    inc = np.clip(np.linspace(0, 85, n_s) + rng.normal(0, 0.2, n_s), 0, 180)
    azi = 120 + np.cumsum(rng.normal(0, 0.05, n_s))
    gr = rng.uniform(15, 140, n_l)
    phi = rng.uniform(0.05, 0.3, n_l)
    rt = rng.uniform(0.5, 200, n_l)

    cases = {
        f"minimum_curvature, {n_s:,} stations": lambda: minimum_curvature(
            md,
            inc,
            azi,
            length_unit="m",
            azimuth_reference="true",
            start_east=0.0,
            start_north=0.0,
            start_tvd=0.0,
        ),
        f"gamma_ray_index + vsh_larionov_tertiary, {n_l:,} samples": lambda: (
            pp.vsh_larionov_tertiary(
                pp.gamma_ray_index(gr, gr_min_api=15, gr_max_api=140, clip=True)["igr"]
            )
        ),
        f"archie_water_saturation, {n_l:,} samples": lambda: pp.archie_water_saturation(
            phi, rt, rw_ohm_m=0.05, a=1.0, m=2.0, n=2.0, clip=True
        ),
    }
    rows = [
        f"Machine: {platform.machine()} · Python {platform.python_version()} · "
        f"NumPy {np.__version__}",
        "",
        "| Case | Best of 5 (ms) |",
        "|---|---|",
    ]
    for name, fn in cases.items():
        t = min(timeit.repeat(fn, number=1, repeat=5)) * 1e3
        rows.append(f"| {name} | {t:.2f} |")
    out = ROOT / "docs" / "validation" / "bench.md"
    out.write_text("\n".join(rows) + "\n")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
