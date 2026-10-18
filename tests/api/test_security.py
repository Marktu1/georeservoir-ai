"""Basic security tests (Phase 3 gate): authentication, per-project authorisation,
limits, timeouts, no paths/code accepted, no sensitive data in errors or logs."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from georeservoir.api import ApiKey, Settings, create_app, hash_token, load_settings
from georeservoir.api.__main__ import main as cli
from georeservoir.engineering import petrophysics
from tests.api.conftest import AUTH, PROJECT, TOKEN, TOKEN_CALC_ONLY

VSH = f"/api/v1/projects/{PROJECT}/calc/petrophysics/vsh"
LAS_URL = f"/api/v1/projects/{PROJECT}/data/las"
LAS = Path(__file__).parents[1] / "data" / "las" / "sample_2.0.las"
GOOD = {"igr": [0.5], "method": "steiber"}


# ---------------------------------------------------------------- authentication
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"X-API-Key": TOKEN},
    ],
)
def test_requests_without_valid_key_are_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    r = client.post(VSH, headers=headers, json=GOOD)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"]["message"] == "missing or invalid API key"


def test_methods_listing_needs_auth(client: TestClient) -> None:
    assert client.get(f"/api/v1/projects/{PROJECT}/methods").status_code == 401


# ---------------------------------------------------------------- authorisation
@pytest.mark.parametrize("project", ["other-project", "BLOCK-17", "block_17x", "a" * 70])
def test_projects_outside_key_scope_are_forbidden(client: TestClient, project: str) -> None:
    r = client.post(f"/api/v1/projects/{project}/calc/petrophysics/vsh", headers=AUTH, json=GOOD)
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "not allowed for this project"


def test_path_like_project_ids_never_reach_a_handler(client: TestClient) -> None:
    for p in ("..", "%2e%2e", "..%2F..%2Fetc", "block-17%2F..%2Fother"):
        r = client.post(f"/api/v1/projects/{p}/calc/petrophysics/vsh", headers=AUTH, json=GOOD)
        assert r.status_code in (403, 404)


def test_upload_scope_is_enforced(client: TestClient) -> None:
    with LAS.open("rb") as f:
        r = client.post(
            LAS_URL,
            headers={"Authorization": f"Bearer {TOKEN_CALC_ONLY}"},
            files={"file": ("a.las", f, "text/plain")},
        )
    assert r.status_code == 403
    ok = client.post(VSH, headers={"Authorization": f"Bearer {TOKEN_CALC_ONLY}"}, json=GOOD)
    assert ok.status_code == 200


# ---------------------------------------------------------------- input limits
def test_body_size_limit_by_header_and_by_stream(
    client_factory: Callable[..., TestClient],
) -> None:
    c = client_factory(max_body_bytes=2048)
    big = {"igr": [0.5] * 2000, "method": "steiber"}
    r = c.post(VSH, headers=AUTH, json=big)
    assert r.status_code == 413 and r.json()["error"]["type"] == "PayloadTooLarge"

    def chunks() -> Any:  # no Content-Length: limit enforced while streaming
        yield b'{"igr": ['
        for _ in range(2000):
            yield b"0.5,"
        yield b'0.5], "method": "steiber"}'

    r = c.post(VSH, headers={**AUTH, "content-type": "application/json"}, content=chunks())
    assert r.status_code == 413


def test_upload_size_limit(client_factory: Callable[..., TestClient]) -> None:
    c = client_factory(max_upload_bytes=1000)
    r = c.post(LAS_URL, headers=AUTH, files={"file": ("big.las", b"x" * 5000, "text/plain")})
    assert r.status_code == 413


def test_array_length_limit_and_mc_sample_cap(client_factory: Callable[..., TestClient]) -> None:
    c = client_factory(max_array_len=10, mc_max_samples=1000)
    r = c.post(VSH, headers=AUTH, json={"igr": [0.5] * 11, "method": "steiber"})
    assert r.status_code == 422 and "at most 10" in r.json()["error"]["message"]
    mc = {
        "porosity": {"kind": "fixed", "value": 0.2},
        "rt_ohm_m": {"kind": "fixed", "value": 20},
        "rw_ohm_m": {"kind": "fixed", "value": 0.05},
        "a": {"kind": "fixed", "value": 1},
        "m": {"kind": "fixed", "value": 2},
        "n": {"kind": "fixed", "value": 2},
        "clip": False,
        "n_samples": 5000,
        "seed": 1,
    }
    r = c.post(f"/api/v1/projects/{PROJECT}/calc/uncertainty/mc-archie-sw", headers=AUTH, json=mc)
    assert r.status_code == 422 and "at most 1000" in r.json()["error"]["message"]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"igr": [NaN], "method": "steiber"}',
        b'{"igr": [Infinity], "method": "steiber"}',
        b'{"igr": [0.5], "method": "steiber", "extra": 1}',
        b'{"igr": [0.5], "method": "__import__(\'os\')"}',
        b'{"igr": "0.5", "method": "steiber"}',
        b"not json",
    ],
)
def test_malformed_or_unexpected_input_is_422(client: TestClient, raw: bytes) -> None:
    r = client.post(VSH, headers={**AUTH, "content-type": "application/json"}, content=raw)
    assert r.status_code == 422


def test_bool_flags_are_strict(client: TestClient) -> None:
    r = client.post(
        f"/api/v1/projects/{PROJECT}/calc/petrophysics/gamma-ray-index",
        headers=AUTH,
        json={"gr_api": [50], "gr_min_api": 20, "gr_max_api": 120, "clip": 1},
    )
    assert r.status_code == 422


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    secret = "SECRET-VALUE-123"
    r = client.post(VSH, headers=AUTH, json={"igr": [secret], "method": "steiber"})
    assert r.status_code == 422 and secret not in r.text


# ---------------------------------------------------------------- no paths, no code
def _request_fields(spec: dict[str, Any]) -> set[str]:
    """All property names reachable from request bodies (JSON and multipart)."""
    comps = spec["components"]["schemas"]
    seen: set[str] = set()
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                key = ref.rsplit("/", 1)[1]
                if key not in seen:
                    seen.add(key)
                    walk(comps[key])
            names.update(node.get("properties", {}).keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for item in spec["paths"].values():
        for op in item.values():
            walk(op.get("requestBody", {}))
    return names


def test_no_endpoint_accepts_paths_or_code(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    fields = {f.lower() for f in _request_fields(spec)}
    assert "file" in fields and "igr" in fields  # the walk does reach request models
    forbidden = {
        "path",
        "file_path",
        "filepath",
        "directory",
        "dir",
        "code",
        "script",
        "expression",
        "eval",
        "url",
        "command",
        "module",
        "callable",
    }
    assert not (fields & forbidden), fields & forbidden
    params = {
        p["name"]
        for item in spec["paths"].values()
        for op in item.values()
        for p in op.get("parameters", [])
    }
    assert params <= {"project_id"}


def test_uploaded_filename_cannot_escape_temp_dir(client: TestClient, tmp_path: Path) -> None:
    before = set(Path(os.path.realpath("/tmp")).glob("georeservoir-upload-*"))
    with LAS.open("rb") as f:
        r = client.post(
            LAS_URL, headers=AUTH, files={"file": ("../../../../tmp/evil.las", f, "text/plain")}
        )
    assert r.status_code == 200
    assert r.json()["provenance"]["file_name"] == "evil.las"
    assert not Path("/tmp/evil.las").exists()
    after = set(Path(os.path.realpath("/tmp")).glob("georeservoir-upload-*"))
    assert after <= before  # private temp dir removed after parsing


# ---------------------------------------------------------------- rate limit, timeout
def test_rate_limit(client_factory: Callable[..., TestClient]) -> None:
    c = client_factory(rate_limit_per_minute=2)
    codes = [c.post(VSH, headers=AUTH, json=GOOD).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = c.post(VSH, headers=AUTH, json=GOOD)
    assert int(r.headers["retry-after"]) >= 1


def test_calculation_timeout(
    client_factory: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    def slow(*a: Any, **k: Any) -> Any:
        time.sleep(0.5)
        return petrophysics.vsh_steiber([0.5])

    monkeypatch.setitem(
        __import__("georeservoir.api.routes", fromlist=["VSH"]).VSH, "steiber", slow
    )
    c = client_factory(calc_timeout_s=0.05)
    r = c.post(VSH, headers=AUTH, json=GOOD)
    assert r.status_code == 504 and r.json()["error"]["type"] == "CalculationTimeout"


# ---------------------------------------------------------------- errors and logs
def test_internal_errors_do_not_leak_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("database password is hunter2")

    monkeypatch.setitem(
        __import__("georeservoir.api.routes", fromlist=["VSH"]).VSH, "steiber", boom
    )
    r = client.post(VSH, headers=AUTH, json=GOOD)
    assert r.status_code == 500
    assert r.json()["error"]["message"] == "internal error" and "hunter2" not in r.text


def test_logs_contain_no_secrets_or_payloads(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="georeservoir.api")
    client.post(VSH, headers=AUTH, json={"igr": [0.123456789], "method": "steiber"})
    with LAS.open("rb") as f:
        client.post(LAS_URL, headers=AUTH, files={"file": ("client-secret-name.las", f)})
    client.post(VSH, headers={"Authorization": "Bearer guessed-token-999"}, json=GOOD)
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert TOKEN not in text and "guessed-token-999" not in text
    assert "0.123456789" not in text and "client-secret-name" not in text
    assert "Bearer" not in text
    lines = [
        json.loads(rec.getMessage())
        for rec in caplog.records
        if rec.name == "georeservoir.api.access"
    ]
    assert {line["key_id"] for line in lines} >= {"analyst", None}
    assert all(
        set(line)
        == {"request_id", "method", "path", "status", "duration_ms", "key_id", "project_id"}
        for line in lines
    )


def test_security_headers(client: TestClient) -> None:
    r = client.post(VSH, headers=AUTH, json=GOOD)
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert (
        h["cache-control"] == "no-store" and "default-src 'none'" in h["content-security-policy"]
    )
    assert len(h["x-request-id"]) == 32
    assert "access-control-allow-origin" not in h  # no CORS unless configured


def test_docs_can_be_disabled(client_factory: Callable[..., TestClient]) -> None:
    assert client_factory(enable_docs=False).get("/api/v1/docs").status_code == 404
    assert client_factory().get("/api/v1/docs").status_code == 200


# ---------------------------------------------------------------- configuration
def test_settings_validation(tmp_path: Path) -> None:
    h = hash_token("t" * 43)
    with pytest.raises(ValueError, match="sha256"):
        ApiKey("k", "nothex", frozenset(), frozenset({"calc"}))
    with pytest.raises(ValueError, match="project"):
        ApiKey("k", h, frozenset({"../x"}), frozenset({"calc"}))
    with pytest.raises(ValueError, match="scope"):
        ApiKey("k", h, frozenset(), frozenset({"admin"}))  # type: ignore[arg-type]
    k = ApiKey("k", h, frozenset({"p"}), frozenset({"calc"}))
    with pytest.raises(ValueError, match="duplicate"):
        Settings(keys=(k, k))
    with pytest.raises(ValueError, match="calc_timeout_s"):
        Settings(keys=(), calc_timeout_s=0)
    with pytest.raises(ValueError, match="KEYS_FILE"):
        load_settings({})
    f = tmp_path / "keys.json"
    f.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "k",
                        "sha256": h.upper(),
                        "projects": ["p"],
                        "scopes": ["calc", "upload"],
                    }
                ]
            }
        )
    )
    st = load_settings(
        {
            "GEORESERVOIR_API_KEYS_FILE": str(f),
            "GEORESERVOIR_MAX_ARRAY_LEN": "50",
            "GEORESERVOIR_ENABLE_DOCS": "0",
        }
    )
    assert st.max_array_len == 50 and not st.enable_docs and st.keys[0].sha256 == h
    with pytest.raises(ValueError, match="keys file"):
        f.write_text("[]")
        load_settings({"GEORESERVOIR_API_KEYS_FILE": str(f)})


def test_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["new-key", "laptop"]) == 0
    out = capsys.readouterr().out
    token = out.splitlines()[1]
    assert len(token) >= 43 and hash_token(token) in out
    assert cli(["openapi"]) == 0
    assert '"openapi"' in capsys.readouterr().out
    assert cli(["bogus"]) == 2


def test_app_without_keys_rejects_everything() -> None:
    c = TestClient(create_app(Settings(keys=())))
    assert c.post(VSH, headers=AUTH, json=GOOD).status_code == 401
