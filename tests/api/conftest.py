"""Shared fixtures for API tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from georeservoir.api import ApiKey, Settings, create_app, hash_token

TOKEN = "test-token-" + "x" * 40
TOKEN_CALC_ONLY = "calc-only-" + "y" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PROJECT = "block-17"


def make_settings(**kw: Any) -> Settings:
    keys = (
        ApiKey(
            "analyst",
            hash_token(TOKEN),
            frozenset({PROJECT, "isptec-demo"}),
            frozenset({"calc", "upload"}),
        ),
        ApiKey(
            "calc-only", hash_token(TOKEN_CALC_ONLY), frozenset({PROJECT}), frozenset({"calc"})
        ),
    )
    return Settings(keys=keys, **kw)


@pytest.fixture
def client_factory() -> Callable[..., TestClient]:
    def make(**kw: Any) -> TestClient:
        return TestClient(create_app(make_settings(**kw)), raise_server_exceptions=False)

    return make


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory()
