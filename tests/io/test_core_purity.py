"""The numerical core must not import optional I/O dependencies (spec §4.1.6/7)."""

from __future__ import annotations

import subprocess
import sys


def test_core_does_not_import_lasio() -> None:
    code = (
        "import sys; import georeservoir.engineering.well_path, "
        "georeservoir.engineering.petrophysics, georeservoir.engineering.dca, "
        "georeservoir.engineering.nodal, georeservoir.engineering.bourdet, "
        "georeservoir.engineering.material_balance, georeservoir.engineering.uncertainty; "
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "('lasio', 'pandas', 'requests', 'http', 'sqlite3')]; print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
