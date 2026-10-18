"""FastAPI application factory: middleware, error mapping, safe logging, routes."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from georeservoir import __version__
from georeservoir.api.config import Settings
from georeservoir.api.security import RateLimiter
from georeservoir.common.exceptions import GeoReservoirError

__all__ = ["create_app"]

ACCESS_LOG = logging.getLogger("georeservoir.api.access")
ERROR_LOG = logging.getLogger("georeservoir.api.error")
#: multipart framing overhead allowed on top of max_upload_bytes
UPLOAD_OVERHEAD = 64 * 1024

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


class GuardMiddleware:
    """Request id, body-size limit (streamed), security headers and a safe access log.

    The access log records method, path, status, duration, request id, key id and project
    id — never request bodies, query strings, file names or the Authorization header.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = rid
        path: str = scope.get("path", "")
        limit = (
            self.settings.max_upload_bytes + UPLOAD_OVERHEAD
            if "/data/" in path
            else self.settings.max_body_bytes
        )
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
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
                if not (path.endswith("/docs") or path.endswith("/redoc")):
                    hdrs.append(API_CSP)
                hdrs.append((b"x-request-id", rid.encode()))
                message["headers"] = hdrs
            await send(message)

        async def send_guarded(message: Message) -> None:
            # once the body limit was hit, whatever the app answers (e.g. a 400 from body
            # parsing) is replaced by a 413
            if too_large["v"]:
                if message["type"] == "http.response.start":
                    await _send_413()
                return
            await send_wrapped(message)

        async def _send_413() -> None:
            resp = _error_response(
                413, "PayloadTooLarge", f"request body exceeds {limit} bytes", rid
            )
            await resp(scope, receive, send_wrapped)

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
            cl = headers.get("content-length")
            if cl is not None and cl.isdigit() and int(cl) > limit:
                too_large["v"] = True
                raise _TooLargeError
            await self.app(scope, receive_wrapped, send_guarded)
        except _TooLargeError:
            if not started["v"]:
                await _send_413()
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


def _error_response(
    status: int, etype: str, message: str, rid: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={"error": {"type": etype, "message": message, "request_id": rid}},
    )


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
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs" if docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.calc_limiter = anyio.CapacityLimiter(settings.max_concurrent_calcs)

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

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
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

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        ERROR_LOG.error(json.dumps({"request_id": _rid(request), "exception": type(exc).__name__}))
        return _error_response(500, "InternalError", "internal error", _rid(request))

    from georeservoir.api.routes import register

    register(app)
    app.add_middleware(GuardMiddleware, settings=settings)
    return app
