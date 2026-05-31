"""Schwab client factory wiring."""

from __future__ import annotations

import json

import pytest

from market_gateway.app.config import Settings
from market_gateway.schwab.client import StubSchwabClient
from market_gateway.schwab.factory import create_schwab_market_client


@pytest.mark.asyncio
async def test_factory_returns_stub_when_live_disabled() -> None:
    s = Settings(
        market_gateway_api_key="k",
        redis_url="redis://localhost:6379/0",
        enable_schwab_live_data=False,
    )
    c = await create_schwab_market_client(s)
    assert isinstance(c, StubSchwabClient)


@pytest.mark.asyncio
async def test_factory_returns_stub_when_credentials_missing() -> None:
    s = Settings(
        market_gateway_api_key="k",
        redis_url="redis://localhost:6379/0",
        enable_schwab_live_data=True,
        schwab_client_id="",
        schwab_client_secret="",
        schwab_token_file="",
    )
    c = await create_schwab_market_client(s)
    assert isinstance(c, StubSchwabClient)


@pytest.mark.asyncio
async def test_factory_returns_stub_when_token_file_invalid_json(
    tmp_path,
) -> None:
    bad = tmp_path / "token.json"
    bad.write_text("not-json{{{", encoding="utf-8")
    s = Settings(
        market_gateway_api_key="k",
        redis_url="redis://localhost:6379/0",
        enable_schwab_live_data=True,
        schwab_client_id="cid",
        schwab_client_secret="secret",
        schwab_token_file=str(bad),
    )
    c = await create_schwab_market_client(s)
    assert isinstance(c, StubSchwabClient)


@pytest.mark.asyncio
async def test_factory_returns_stub_when_token_missing_schwab_metadata(
    tmp_path,
) -> None:
    """Valid JSON but not a schwab-py token wrapper (no creation_timestamp / token)."""
    bad = tmp_path / "token.json"
    bad.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    s = Settings(
        market_gateway_api_key="k",
        redis_url="redis://localhost:6379/0",
        enable_schwab_live_data=True,
        schwab_client_id="cid",
        schwab_client_secret="secret",
        schwab_token_file=str(bad),
    )
    c = await create_schwab_market_client(s)
    assert isinstance(c, StubSchwabClient)
