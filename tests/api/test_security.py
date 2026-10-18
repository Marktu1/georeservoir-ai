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


def test_docs_and_openapi_can_be_disabled(client_factory: Callable[..., TestClient]) -> None:
    off = client_factory(enable_docs=False)
    assert off.get("/api/v1/docs").status_code == 404
    assert off.get("/api/v1/openapi.json").status_code == 404
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
    with pytest.raises(ValueError, match="queue_timeout_s"):
        Settings(keys=(), queue_timeout_s=-1)
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


# ---------------------------------------------------------------- review regressions
def test_auth_is_checked_before_the_body_is_read(client: TestClient) -> None:
    r = client.post(VSH, headers={"content-type": "application/json"}, content=b"{broken")
    assert r.status_code == 401  # not 422: the body was never parsed
    r = client.post(LAS_URL, files={"file": ("big.las", b"x" * 3_000_000)})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "value",
    [
        f"Bearer  {TOKEN}",
        f"Bearer {TOKEN} ",
        f" Bearer {TOKEN}",
        f"Bearer {TOKEN} extra",
        f"Bearer\t{TOKEN}",
    ],
)
def test_malformed_authorization_values(client: TestClient, value: str) -> None:
    assert client.post(VSH, headers={"Authorization": value}, json=GOOD).status_code == 401


def test_scheme_is_case_insensitive_and_duplicate_header_refused(client: TestClient) -> None:
    assert (
        client.post(VSH, headers={"Authorization": f"bearer {TOKEN}"}, json=GOOD).status_code
        == 200
    )
    r = client.post(
        VSH,
        headers=[("Authorization", f"Bearer {TOKEN}"), ("Authorization", f"Bearer {TOKEN}")],
        json=GOOD,
    )
    assert r.status_code == 401


def test_failed_auth_and_forbidden_requests_are_rate_limited(
    client_factory: Callable[..., TestClient],
) -> None:
    c = client_factory(rate_limit_per_minute=3)
    codes = [
        c.post(VSH, headers={"Authorization": f"Bearer guess-{i}"}, json=GOOD).status_code
        for i in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    c = client_factory(rate_limit_per_minute=3)
    other = "/api/v1/projects/other/calc/petrophysics/vsh"
    codes = [c.post(other, headers=AUTH, json=GOOD).status_code for _ in range(5)]
    assert codes[:3] == [403, 403, 403] and codes[3:] == [429, 429]


def test_body_limit_is_chosen_by_route_not_substring(
    client_factory: Callable[..., TestClient],
) -> None:
    c = client_factory(max_body_bytes=2048, max_upload_bytes=10_000_000)
    r = c.post(
        "/api/v1/projects/data/calc/petrophysics/vsh",
        headers=AUTH,
        json={"igr": [0.5] * 2000, "method": "steiber"},
    )
    assert r.status_code == 413


def test_500_has_security_headers_and_request_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("secret")

    monkeypatch.setitem(
        __import__("georeservoir.api.routes", fromlist=["VSH"]).VSH, "steiber", boom
    )
    r = client.post(VSH, headers=AUTH, json=GOOD)
    assert r.status_code == 500
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"] == r.json()["error"]["request_id"]


def test_404_and_405_use_typed_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["type"] == "HTTPError"
    r = client.get(VSH, headers=AUTH)
    assert r.status_code == 405 and "error" in r.json()


@pytest.mark.parametrize("bad", [True, "20", [0.5], None])
def test_numbers_are_strict(client: TestClient, bad: Any) -> None:
    body = {
        "porosity": [0.2],
        "rt_ohm_m": [20],
        "rw_ohm_m": bad,
        "a": 1,
        "m": 2,
        "n": 2,
        "clip": False,
    }
    r = client.post(
        f"/api/v1/projects/{PROJECT}/calc/petrophysics/archie-sw", headers=AUTH, json=body
    )
    assert r.status_code == 422
    r = client.post(VSH, headers=AUTH, json={"igr": [True], "method": "steiber"})
    assert r.status_code == 422
    r = client.post(
        VSH,
        headers={**AUTH, "content-type": "application/json"},
        content=b'{"igr": [1e400], "method": "steiber"}',
    )
    assert r.status_code == 422


def test_timed_out_calculations_cannot_accumulate(
    client_factory: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    running = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(*a: Any, **k: Any) -> Any:
        with lock:
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
        time.sleep(0.4)
        with lock:
            running["now"] -= 1
        return petrophysics.vsh_steiber([0.5])

    monkeypatch.setitem(
        __import__("georeservoir.api.routes", fromlist=["VSH"]).VSH, "steiber", slow
    )
    c = client_factory(max_concurrent_calcs=1, calc_timeout_s=0.05, queue_timeout_s=0.0)
    codes = [c.post(VSH, headers=AUTH, json=GOOD).status_code for _ in range(5)]
    assert codes[0] == 504 and set(codes[1:]) <= {503, 504}
    assert 503 in codes  # the abandoned thread still holds the only slot
    time.sleep(0.5)
    assert running["max"] == 1


def test_queue_wait_does_not_count_as_calculation_time(
    client_factory: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    def slow(*a: Any, **k: Any) -> Any:
        time.sleep(0.3)
        return petrophysics.vsh_steiber([0.5])

    monkeypatch.setitem(
        __import__("georeservoir.api.routes", fromlist=["VSH"]).VSH, "steiber", slow
    )
    c = client_factory(max_concurrent_calcs=1, calc_timeout_s=0.5, queue_timeout_s=5.0)
    out: list[int] = []

    def call() -> None:
        out.append(c.post(VSH, headers=AUTH, json=GOOD).status_code)

    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert out == [200, 200, 200]  # third waited ~0.6 s in the queue, then ran 0.3 s


def test_only_one_file_part_accepted(client: TestClient) -> None:
    data = LAS.read_bytes()
    r = client.post(
        LAS_URL, headers=AUTH, files=[("file", ("a.las", data)), ("file", ("b.las", data))]
    )
    assert r.status_code == 422 and "exactly one" in r.json()["error"]["message"]


def test_rate_limiter_memory_is_bounded() -> None:
    from georeservoir.api.security import MAX_BUCKETS, RateLimiter

    rl = RateLimiter(10)
    for i in range(MAX_BUCKETS + 50):
        rl.allow(f"addr:{i}")
    assert len(rl._state) == MAX_BUCKETS
