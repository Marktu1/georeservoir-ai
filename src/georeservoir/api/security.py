"""Authentication (bearer API keys), per-project authorisation, rate limiting and the
calculation-slot pool."""

from __future__ import annotations

import hmac
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, TypeVar

import anyio

from georeservoir.api.config import PROJECT_ID_RE, ApiKey, Scope, Settings, hash_token

__all__ = [
    "CalcSlots",
    "Principal",
    "RateLimiter",
    "ServerBusyError",
    "authorize_scope",
    "lookup_key",
]

T = TypeVar("T")
#: Maximum number of buckets kept (oldest evicted) so anonymous traffic cannot grow memory.
MAX_BUCKETS: Final[int] = 10_000


@dataclass(frozen=True, slots=True)
class Principal:
    key_id: str
    project_id: str


class RateLimiter:
    """Token bucket per identity (``key:<id>`` or ``addr:<ip>``), in-process, bounded."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._state: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, identity: str) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.pop(identity, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._state[identity] = (tokens, now)
            while len(self._state) > MAX_BUCKETS:
                self._state.popitem(last=False)
            return (True, 0.0) if allowed else (False, (1.0 - tokens) / self.rate)


def lookup_key(authorization: str, settings: Settings) -> ApiKey | None:
    """Key for an ``Authorization: Bearer <token>`` value, or None.

    Exactly one space-separated bearer token is accepted (no surrounding whitespace, no
    duplicated header). Comparison is constant-time over all keys.
    """
    scheme, sep, token = authorization.partition(" ")
    if (
        sep != " "
        or scheme.lower() != "bearer"
        or not token
        or token != token.strip()
        or " " in token
        or "\x00" in authorization
    ):
        return None
    digest = hash_token(token)
    found: ApiKey | None = None
    for key in settings.keys:  # no early exit: no timing signal about which key matched
        if hmac.compare_digest(key.sha256, digest):
            found = key
    return found


def authorize_scope(key: ApiKey, project_id: str, scope: Scope) -> bool:
    """True only if the project id is well-formed and both project and scope are granted."""
    return (
        bool(PROJECT_ID_RE.match(project_id))
        and project_id in key.projects
        and scope in key.scopes
    )


class ServerBusyError(Exception):
    """No calculation slot became free within the queue timeout."""


class CalcSlots:
    """At most ``n`` calculations **running** at once.

    A slot is taken before the worker thread starts and released by the thread itself
    when the calculation really finishes — also after the request has timed out — so
    abandoned threads cannot accumulate beyond ``n`` (A-026).
    """

    def __init__(self, n: int) -> None:
        self._sem = threading.BoundedSemaphore(n)
        self.n = n

    async def run(
        self, fn: Callable[[], T], *, queue_timeout_s: float, calc_timeout_s: float
    ) -> T:
        deadline = time.monotonic() + queue_timeout_s
        while not self._sem.acquire(blocking=False):  # waiting is not calculation time
            if time.monotonic() >= deadline:
                raise ServerBusyError
            await anyio.sleep(0.01)

        # Exactly one party releases the slot: the worker thread if it starts, otherwise
        # the canceller. ``claim`` decides who, under a lock.
        lock = threading.Lock()
        claimed = {"v": False}

        def claim() -> bool:
            with lock:
                if claimed["v"]:
                    return False
                claimed["v"] = True
                return True

        def work() -> T:
            if not claim():  # request was cancelled before this thread started
                raise ServerBusyError
            try:
                return fn()
            finally:
                self._sem.release()

        try:
            with anyio.fail_after(calc_timeout_s):
                return await anyio.to_thread.run_sync(work, abandon_on_cancel=True)
        except BaseException:
            if claim():  # the thread never started: free the slot here
                self._sem.release()
            raise

    @property
    def free(self) -> int:
        """Slots currently free (diagnostics and tests)."""
        return self._sem._value
