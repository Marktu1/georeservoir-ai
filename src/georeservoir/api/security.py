"""Authentication (bearer API keys), per-project authorisation and rate limiting."""

from __future__ import annotations

import hmac
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from georeservoir.api.config import PROJECT_ID_RE, ApiKey, Scope, Settings, hash_token

__all__ = ["Principal", "RateLimiter", "authenticate", "authorize"]


@dataclass(frozen=True, slots=True)
class Principal:
    key_id: str
    project_id: str


class RateLimiter:
    """Token bucket per key (in-process; a multi-worker deployment needs a shared store)."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key_id, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self._state[key_id] = (tokens - 1.0, now)
                return True, 0.0
            self._state[key_id] = (tokens, now)
            return False, (1.0 - tokens) / self.rate


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="missing or invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate(request: Request, settings: Settings) -> ApiKey:
    """Resolve the bearer token to a key. Comparison is constant-time over all keys."""
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    digest = hash_token(token.strip())
    found: ApiKey | None = None
    for key in settings.keys:  # iterate all keys: no early exit timing signal
        if hmac.compare_digest(key.sha256, digest):
            found = key
    if found is None:
        raise _unauthorized()
    return found


def authorize(key: ApiKey, project_id: str, scope: Scope) -> Principal:
    """403 unless the key has the scope and the project (same answer for unknown projects)."""
    if (
        not PROJECT_ID_RE.match(project_id)
        or project_id not in key.projects
        or scope not in key.scopes
    ):
        raise HTTPException(status_code=403, detail="not allowed for this project")
    return Principal(key.key_id, project_id)
