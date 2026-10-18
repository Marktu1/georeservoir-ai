"""Write docs/api/openapi-v1.json (the committed API contract snapshot).

Usage:  python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from georeservoir.api import Settings, create_app  # noqa: E402


def main() -> None:
    spec = create_app(Settings(keys=())).openapi()
    out = ROOT / "docs" / "api" / "openapi-v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
