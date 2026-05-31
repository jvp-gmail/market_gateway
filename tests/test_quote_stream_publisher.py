from __future__ import annotations

from datetime import date

import pytest
from fakeredis.aioredis import FakeRedis

from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import OptionContractQuote, QuoteSnapshot, StreamEventType
from market_gateway.app.core.time_utils import utc_now
from market_gateway.app.services.quote_stream_publisher import publish_equity_quote, publish_option_quote


@pytest.mark.asyncio
async def test_publish_equity_quote_round_trip() -> None:
    fake = FakeRedis(decode_responses=True)
    bus = EventBus(fake, "stream:qsp_test", xread_block_ms=10)
    now = utc_now()
    snap = QuoteSnapshot(
        symbol="SPY",
        event_ts=now,
        received_ts=now,
        bid=100.0,
        ask=100.05,
        last=100.02,
        mark=100.03,
        source="test",
    )
    await publish_equity_quote(bus, snap)
    recent = await bus.recent(count=5)
    assert len(recent) == 1
    assert recent[0].event_type == StreamEventType.EQUITY_QUOTE
    q = recent[0].payload["quote"]
    assert q["symbol"] == "SPY"
    assert q["bid"] == 100.0


@pytest.mark.asyncio
async def test_publish_option_quote_round_trip() -> None:
    fake = FakeRedis(decode_responses=True)
    bus = EventBus(fake, "stream:qsp_opt", xread_block_ms=10)
    now = utc_now()
    oc = OptionContractQuote(
        option_symbol="SPY_20260619C00400000",
        underlying_symbol="SPY",
        expiration=date(2026, 6, 19),
        strike=400.0,
        option_type="CALL",
        event_ts=now,
        received_ts=now,
        bid=1.1,
        ask=1.2,
        delta=0.5,
        source="test",
    )
    await publish_option_quote(bus, oc)
    recent = await bus.recent(count=5)
    assert len(recent) == 1
    assert recent[0].event_type == StreamEventType.OPTION_QUOTE
    q = recent[0].payload["quote"]
    assert q["option_symbol"] == "SPY_20260619C00400000"
    assert q["delta"] == 0.5
