"""Command line: ``python -m georeservoir.api [serve|new-key|openapi]``.

serve    run the API with uvicorn (settings from environment variables)
new-key  print a new random token and the JSON entry (with its SHA-256) for the keys file
openapi  print the OpenAPI document (no keys needed)
"""

from __future__ import annotations

import json
import logging
import os
import sys

from georeservoir.api.app import create_app
from georeservoir.api.config import Settings, hash_token, load_settings, new_token


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "serve"
    if cmd == "new-key":
        token = new_token()
        entry = {
            "key_id": args[1] if len(args) > 1 else "new-key",
            "sha256": hash_token(token),
            "projects": [],
            "scopes": ["calc"],
        }
        print("TOKEN (shown once; store it securely, it is not saved anywhere):")
        print(token)
        print("Keys-file entry (add project ids and scopes):")
        print(json.dumps(entry, indent=2))
        return 0
    if cmd == "openapi":
        print(json.dumps(create_app(Settings(keys=())).openapi(), indent=2, sort_keys=True))
        return 0
    if cmd == "serve":
        import uvicorn

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        app = create_app(load_settings())
        uvicorn.run(
            app,
            host=os.environ.get("GEORESERVOIR_HOST", "127.0.0.1"),
            port=int(os.environ.get("GEORESERVOIR_PORT", "8000")),
            access_log=False,
            server_header=False,
            proxy_headers=False,
        )
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
