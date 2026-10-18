"""FastAPI application factory: guard middleware, error mapping, safe logging, routes."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from georeservoir import __version__
from georeservoir.api.config import Scope as KeyScope
from georeservoir.api.config import Settings
from georeservoir.api.security import (
    CalcSlots,
    RateLimiter,
    ServerBusyError,
    authorize_scope,
    lookup_key,
)
from georeservoir.common.exceptions import GeoReservoirError

__all__ = ["create_app"]

ACCESS_LOG = logging.getLogger("georeservoir.api.access")
ERROR_LOG = logging.getLogger("georeservoir.api.error")
#: multipart framing overhead allowed on top of max_upload_bytes
UPLOAD_OVERHEAD: Final[int] = 64 * 1024
#: /api/v1/projects/{project_id}/{kind}/...  (kind: calc | data | methods)
PROTECTED: Final[re.Pattern[str]] = re.compile(r"^/api/v1/projects/([^/]+)/(calc|data|methods)")
UPLOAD_ROUTE: Final[re.Pattern[str]] = re.compile(r"^/api/v1/projects/[^/]+/data/(las|survey)$")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
]
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")


class _TooLargeError(Exception):
    pass


def _error_response(
    status: int, etype: str, message: str, rid: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={"error": {"type": etype, "message": message, "request_id": rid}},
    )


class GuardMiddleware:
    """Outermost guard for every HTTP request.

    In order: request id; for project routes, authentication, rate limiting (per key, and
    per client address for failed authentication) and project/scope authorisation —
    **before the body is read**; body-size limit chosen by route (streamed); security
    headers and ``X-Request-ID`` on every response, including 500s; one JSON access-log
    line without bodies, query strings, file names or the Authorization header.
    """

    def __init__(self, app: ASGIApp, settings: Settings, limiter: RateLimiter) -> None:
        self.app = app
        self.settings = settings
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = rid
        path: str = scope.get("path", "")
        upload = bool(UPLOAD_ROUTE.match(path))
        limit = (
            self.settings.max_upload_bytes + UPLOAD_OVERHEAD
            if upload
            else self.settings.max_body_bytes
        )
        headers: dict[str, str] = {}
        for k, v in scope.get("headers", []):
            name = k.decode("latin-1").lower()
            if name == "authorization" and name in headers:
                headers[name] = "\x00multiple"  # several Authorization headers: refuse
            else:
                headers[name] = v.decode("latin-1")
        start = time.perf_counter()
        status_holder = {"status": 500}
        started = {"v": False}
        too_large = {"v": False}

        async def send_wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                started["v"] = True
                status_holder["status"] = int(message["status"])
                hdrs = list(message.get("headers", []))
                hdrs.extend(SECURITY_HEADERS)
                if not path.endswith("/docs"):
                    hdrs.append(API_CSP)
                hdrs.append((b"x-request-id", rid.encode()))
                message["headers"] = hdrs
            await send(message)

        async def respond(resp: JSONResponse) -> None:
            await resp(scope, receive, send_wrapped)

        def too_large_resp() -> JSONResponse:
            return _error_response(
                413, "PayloadTooLarge", f"request body exceeds {limit} bytes", rid
            )

        async def send_guarded(message: Message) -> None:
            if too_large["v"]:  # whatever the app answers after the limit becomes a 413
                if message["type"] == "http.response.start":
                    await respond(too_large_resp())
                return
            await send_wrapped(message)

        received = {"n": 0}

        async def receive_wrapped() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                received["n"] += len(message.get("body", b""))
                if received["n"] > limit:
                    too_large["v"] = True
                    raise _TooLargeError
            return message

        try:
            denial = self._gate(path, headers, scope, state, rid)
            if denial is not None:
                await respond(denial)
                return
            cl = headers.get("content-length")
            if cl is not None and cl.isdigit() and int(cl) > limit:
                too_large["v"] = True
                raise _TooLargeError
            await self.app(scope, receive_wrapped, send_guarded)
        except _TooLargeError:
            if not started["v"]:
                await respond(too_large_resp())
        except Exception as exc:  # anything the app's handlers did not map
            ERROR_LOG.error(json.dumps({"request_id": rid, "exception": type(exc).__name__}))
            if not started["v"]:
                await respond(_error_response(500, "InternalError", "internal error", rid))
        finally:
            ACCESS_LOG.info(
                json.dumps(
                    {
                        "request_id": rid,
                        "method": scope.get("method"),
                        "path": path,
                        "status": status_holder["status"],
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                        "key_id": state.get("key_id"),
                        "project_id": state.get("project_id"),
                    },
                    sort_keys=True,
                )
            )

    def _gate(
        self, path: str, headers: dict[str, str], scope: Scope, state: dict[str, Any], rid: str
    ) -> JSONResponse | None:
        m = PROTECTED.match(path)
        if m is None:
            return None
        project_id, kind = m.group(1), m.group(2)
        client = scope.get("client") or ("unknown", 0)
        key = lookup_key(headers.get("authorization", ""), self.settings)
        if key is None:
            ok, retry = self.limiter.allow(f"addr:{client[0]}")
            if not ok:
                return _error_response(
                    429,
                    "HTTPError",
                    "rate limit exceeded",
                    rid,
                    {"Retry-After": str(max(1, int(retry) + 1))},
                )
            return _error_response(
                401, "HTTPError", "missing or invalid API key", rid, {"WWW-Authenticate": "Bearer"}
            )
        state["key_id"] = key.key_id
        ok, retry = self.limiter.allow(f"key:{key.key_id}")
        if not ok:
            return _error_response(
                429,
                "HTTPError",
                "rate limit exceeded",
                rid,
                {"Retry-After": str(max(1, int(retry) + 1))},
            )
        needed: KeyScope = "upload" if kind == "data" else "calc"
        if not authorize_scope(key, project_id, needed):
            return _error_response(403, "HTTPError", "not allowed for this project", rid)
        state["project_id"] = project_id
        state["authorized"] = (key.key_id, project_id, needed)
        return None


def _rid(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def create_app(settings: Settings) -> FastAPI:
    """Build the API. ``settings`` comes from the operator (``load_settings``)."""
    docs = settings.enable_docs
    app = FastAPI(
        title="GeoReservoir AI API",
        version=__version__,
        summary="Auditable subsurface engineering calculations. Every result is a "
        "CalculationRecord with inputs hash, method, reference and maturity.",
        openapi_url="/api/v1/openapi.json" if docs else None,
        docs_url="/api/v1/docs" if docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.calc_slots = CalcSlots(settings.max_concurrent_calcs)

    @app.exception_handler(GeoReservoirError)
    async def _geo(request: Request, exc: GeoReservoirError) -> JSONResponse:
        return _error_response(422, type(exc).__name__, str(exc), _rid(request))

    @app.exception_handler(NotImplementedError)
    async def _ni(request: Request, exc: NotImplementedError) -> JSONResponse:
        return _error_response(501, "NotImplemented", str(exc), _rid(request))

    @app.exception_handler(RequestValidationError)
    async def _rv(request: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors()[:10]:  # never echo the submitted input values
            loc = ".".join(str(x) for x in err.get("loc", ()))
            parts.append(f"{loc}: {err.get('msg', 'invalid')}")
        return _error_response(422, "RequestValidationError", "; ".join(parts), _rid(request))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        hdrs = dict(exc.headers) if exc.headers else None
        return _error_response(exc.status_code, "HTTPError", str(exc.detail), _rid(request), hdrs)

    @app.exception_handler(TimeoutError)
    async def _timeout(request: Request, exc: TimeoutError) -> JSONResponse:
        return _error_response(
            504,
            "CalculationTimeout",
            f"calculation exceeded {settings.calc_timeout_s} s",
            _rid(request),
        )

    @app.exception_handler(ServerBusyError)
    async def _busy(request: Request, exc: ServerBusyError) -> JSONResponse:
        return _error_response(
            503,
            "ServerBusy",
            "all calculation slots are busy; retry later",
            _rid(request),
            {"Retry-After": "5"},
        )

    from georeservoir.api.routes import register

    register(app)
    app.add_middleware(GuardMiddleware, settings=settings, limiter=app.state.rate_limiter)
    return app
