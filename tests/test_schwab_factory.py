"""Schwab client factory wiring."""

from __future__ import annotations

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
