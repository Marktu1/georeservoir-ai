"""API configuration: limits and API keys (stored only as SHA-256 hashes).

Keys file (JSON, path given by the operator, never by a request)::

    {"keys": [{"key_id": "marcos-laptop",
               "sha256": "<hex sha256 of the token>",
               "projects": ["block-17", "isptec-demo"],
               "scopes": ["calc", "upload"]}]}

Generate a token and its hash with ``python -m georeservoir.api new-key``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "PROJECT_ID_RE",
    "ApiKey",
    "Scope",
    "Settings",
    "hash_token",
    "load_settings",
    "new_token",
]

Scope = Literal["calc", "upload"]
PROJECT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_KEY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_HEX64: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
#: Tokens shorter than this are refused when generating keys (A-025).
MIN_TOKEN_BYTES: Final[int] = 32


def hash_token(token: str) -> str:
    """SHA-256 hex digest of an API token (what the keys file stores)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    """A new random API token (256 bits, URL-safe)."""
    return secrets.token_urlsafe(MIN_TOKEN_BYTES)


@dataclass(frozen=True, slots=True)
class ApiKey:
    """An API key: identifier, token hash, allowed projects and scopes."""

    key_id: str
    sha256: str
    projects: frozenset[str]
    scopes: frozenset[Scope]

    def __post_init__(self) -> None:
        if not _KEY_ID_RE.match(self.key_id):
            raise ValueError(f"key_id {self.key_id!r} is not a valid identifier")
        if not _HEX64.match(self.sha256):
            raise ValueError(f"key {self.key_id!r}: sha256 must be 64 lowercase hex chars")
        bad = [p for p in self.projects if not PROJECT_ID_RE.match(p)]
        if bad:
            raise ValueError(f"key {self.key_id!r}: invalid project id(s) {bad}")
        if not self.scopes <= {"calc", "upload"}:
            raise ValueError(f"key {self.key_id!r}: unknown scope(s) {set(self.scopes)}")


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime limits and keys. All limits are explicit; defaults are conservative."""

    keys: tuple[ApiKey, ...]
    max_body_bytes: int = 10 * 1024 * 1024
    max_upload_bytes: int = 20 * 1024 * 1024
    max_array_len: int = 200_000
    calc_timeout_s: float = 30.0
    max_concurrent_calcs: int = 4
    mc_max_samples: int = 200_000
    rate_limit_per_minute: int = 120
    enable_docs: bool = True
    _by_hash: dict[str, ApiKey] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        ids = [k.key_id for k in self.keys]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate key_id in keys")
        hashes = [k.sha256 for k in self.keys]
        if len(hashes) != len(set(hashes)):
            raise ValueError("duplicate token hash in keys")
        for name in (
            "max_body_bytes",
            "max_upload_bytes",
            "max_array_len",
            "max_concurrent_calcs",
            "mc_max_samples",
            "rate_limit_per_minute",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be >= 1")
        if not self.calc_timeout_s > 0:
            raise ValueError("calc_timeout_s must be > 0")
        object.__setattr__(self, "_by_hash", {k.sha256: k for k in self.keys})

    def key_for_hash(self, digest: str) -> ApiKey | None:
        return self._by_hash.get(digest)


def _parse_keys(data: object) -> tuple[ApiKey, ...]:
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise ValueError('keys file must be a JSON object {"keys": [...]}')
    out = []
    for item in data["keys"]:
        if not isinstance(item, dict):
            raise ValueError("each key must be a JSON object")
        out.append(
            ApiKey(
                key_id=str(item["key_id"]),
                sha256=str(item["sha256"]).lower(),
                projects=frozenset(str(p) for p in item.get("projects", [])),
                scopes=frozenset(item.get("scopes", ["calc"])),
            )
        )
    return tuple(out)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Settings from environment variables (operator-controlled, never from requests).

    ``GEORESERVOIR_API_KEYS_FILE`` (required), and optional integer/float limits:
    ``GEORESERVOIR_MAX_BODY_BYTES``, ``..._MAX_UPLOAD_BYTES``, ``..._MAX_ARRAY_LEN``,
    ``..._CALC_TIMEOUT_S``, ``..._MAX_CONCURRENT_CALCS``, ``..._MC_MAX_SAMPLES``,
    ``..._RATE_LIMIT_PER_MINUTE``, ``..._ENABLE_DOCS`` (0/1).
    """
    e = dict(os.environ) if env is None else env
    path = e.get("GEORESERVOIR_API_KEYS_FILE")
    if not path:
        raise ValueError("GEORESERVOIR_API_KEYS_FILE is not set")
    keys = _parse_keys(json.loads(Path(path).read_text(encoding="utf-8")))
    kw: dict[str, int | float | bool] = {}
    for name, conv in (
        ("max_body_bytes", int),
        ("max_upload_bytes", int),
        ("max_array_len", int),
        ("calc_timeout_s", float),
        ("max_concurrent_calcs", int),
        ("mc_max_samples", int),
        ("rate_limit_per_minute", int),
    ):
        raw = e.get(f"GEORESERVOIR_{name.upper()}")
        if raw is not None:
            kw[name] = conv(raw)
    if "GEORESERVOIR_ENABLE_DOCS" in e:
        kw["enable_docs"] = e["GEORESERVOIR_ENABLE_DOCS"] == "1"
    return Settings(keys=keys, **kw)  # type: ignore[arg-type]
