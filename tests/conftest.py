"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os

# Must be set before Settings() is first constructed in app lifespan.
os.environ.setdefault("MARKET_GATEWAY_API_KEY", "pytest-market-gateway-key")

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient

from market_gateway.app.main import create_app


@pytest.fixture(autouse=True)
def _unit_tests_ignore_repo_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force sample historical store: repo .env may point at real Postgres with other data."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("POSTGRES_PASSWORD", "")


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def client(fake_redis: FakeRedis) -> TestClient:
    with TestClient(create_app(redis_client=fake_redis)) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["MARKET_GATEWAY_API_KEY"]}
