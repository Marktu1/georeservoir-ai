"""End-to-end from a public LAS file to density porosity, keeping the data lineage.

Usage:  python examples/las_to_porosity.py

Uses tests/data/las/sample_2.0.las (public test file from the lasio project, MIT licence;
values are illustrative, not a real well).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from georeservoir.engineering.petrophysics import density_porosity  # noqa: E402
from georeservoir.io.las import read_las  # noqa: E402


def main() -> None:
    log = read_las(ROOT / "tests" / "data" / "las" / "sample_2.0.las", on_error="raise")
    print(log.report.to_markdown())
    mask = log.valid_mask("RHOB")
    rhob = log.values_in("RHOB", "g/cc")[mask]  # kg/m3 in the file → g/cc, exact factor
    rec = density_porosity(rhob, rho_matrix_g_cc=2.65, rho_fluid_g_cc=1.0, clip=False)
    lineage = {
        "source_file": log.provenance.to_dict(),
        "curve": {
            "mnemonic": log.curve("RHOB").mnemonic,
            "unit_raw": log.curve("RHOB").unit_raw,
            "converted_to": "g/cc",
            "samples_used": int(mask.sum()),
        },
        "calculation": rec.to_dict(),
    }
    print(json.dumps(lineage, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
