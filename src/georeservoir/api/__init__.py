"""HTTP API (Phase 3): FastAPI app exposing the scientific core as versioned endpoints.

Install with ``pip install georeservoir[api]``. The numerical core never imports this
package. Every calculation endpoint returns the core's ``CalculationRecord`` unchanged.

Run: ``GEORESERVOIR_API_KEYS_FILE=keys.json python -m georeservoir.api``
"""

from georeservoir.api.app import create_app
from georeservoir.api.config import ApiKey, Settings, hash_token, load_settings

__all__ = ["ApiKey", "Settings", "create_app", "hash_token", "load_settings"]
