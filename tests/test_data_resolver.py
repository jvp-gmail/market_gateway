from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from market_gateway.app.config import Settings
from market_gateway.app.core.models import Bar, DataMode
from market_gateway.app.services.data_resolver import DataResolver, merge_bars_by_preference
from market_gateway.app.services.historical_store import HistoricalStore
from market_gateway.app.services.live_cache import LiveCache
from market_gateway.schwab.client import StubSchwabClient
from fakeredis.aioredis import FakeRedis


def test_merge_bars_historical_wins_on_duplicate_ts() -> None:
    ts = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    hist = [
        Bar(
            symbol="SPY",
            timestamp=ts,
            timeframe="1m",
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
            source="historical",
        )
    ]
    live = [
        Bar(
            symbol="SPY",
            timestamp=ts,
            timeframe="1m",
            open=50,
            high=51,
            low=49,
            close=50,
            volume=2,
            source="live_schwab",
        )
    ]
    merged = merge_bars_by_preference(hist, live)
    assert len(merged) == 1
    assert merged[0].close == 100
    assert merged[0].source == "historical"


class _MockHistorical(HistoricalStore):
    def __init__(self, lf: datetime | None, hist: list[Bar]) -> None:
        self._lf = lf
        self._hist = hist

    async def get_equity_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        _ = symbol, timeframe, start, end
        return list(self._hist)

    async def get_option_bars(
        self, option_symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        _ = option_symbol, timeframe, start, end
        return []

    async def get_last_finalized_timestamp(
        self, symbol: str, timeframe: str
    ) -> datetime | None:
        _ = symbol, timeframe
        return self._lf


@pytest.mark.asyncio
async def test_historical_only_uses_historical_store_only() -> None:
    lf = datetime(2026, 5, 10, 20, 0, tzinfo=UTC)
    hist_bar = Bar(
        symbol="SPY",
        timestamp=lf,
        timeframe="1m",
        open=1,
        high=2,
        low=1,
        close=2,
        volume=1,
        source="historical",
    )
    mh = _MockHistorical(lf, [hist_bar])
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    await live.set_live_bar(
        Bar(
            symbol="SPY",
            timestamp=lf + timedelta(minutes=1),
            timeframe="1m",
            open=9,
            high=9,
            low=9,
            close=9,
            volume=9,
            source="live_schwab",
        )
    )
    settings = Settings(market_gateway_api_key="k", redis_url="redis://localhost:6379/0")
    r = DataResolver(settings, mh, live, StubSchwabClient())
    start = lf - timedelta(hours=1)
    end = lf + timedelta(hours=2)
    out = await r.get_bars("SPY", "1m", start=start, end=end, mode=DataMode.HISTORICAL_ONLY)
    assert len(out.bars) == 1
    assert out.bars[0].source == "historical"


@pytest.mark.asyncio
async def test_live_only_uses_live_cache_only() -> None:
    mh = _MockHistorical(None, [])
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    ts = datetime(2026, 5, 10, 20, 0, tzinfo=UTC)
    await live.set_live_bar(
        Bar(
            symbol="SPY",
            timestamp=ts,
            timeframe="1m",
            open=3,
            high=3,
            low=3,
            close=3,
            volume=3,
            source="live_schwab",
        )
    )
    settings = Settings(market_gateway_api_key="k", redis_url="redis://localhost:6379/0")
    r = DataResolver(settings, mh, live, StubSchwabClient())
    out = await r.get_bars(
        "SPY",
        "1m",
        start=ts - timedelta(minutes=5),
        end=ts + timedelta(minutes=5),
        mode=DataMode.LIVE_ONLY,
    )
    assert len(out.bars) == 1
    assert out.bars[0].source == "live_schwab"


@pytest.mark.asyncio
async def test_canonical_plus_live_stitches_and_sorts() -> None:
    lf = datetime(2026, 5, 10, 15, 0, tzinfo=UTC)
    h1 = Bar(
        symbol="SPY",
        timestamp=lf - timedelta(minutes=1),
        timeframe="1m",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        source="historical",
    )
    h2 = Bar(
        symbol="SPY",
        timestamp=lf,
        timeframe="1m",
        open=2,
        high=2,
        low=2,
        close=2,
        volume=2,
        source="historical",
    )
    mh = _MockHistorical(lf, [h1, h2])
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    l1 = Bar(
        symbol="SPY",
        timestamp=lf + timedelta(minutes=1),
        timeframe="1m",
        open=5,
        high=5,
        low=5,
        close=5,
        volume=5,
        source="live_schwab",
    )
    await live.set_live_bar(l1)
    settings = Settings(market_gateway_api_key="k", redis_url="redis://localhost:6379/0")
    r = DataResolver(settings, mh, live, StubSchwabClient())
    out = await r.get_bars(
        "SPY",
        "1m",
        start=lf - timedelta(minutes=2),
        end=lf + timedelta(minutes=2),
        mode=DataMode.CANONICAL_PLUS_LIVE,
    )
    assert [b.close for b in out.bars] == [1.0, 2.0, 5.0]
    sources = [b.source for b in out.bars]
    assert sources[:2] == ["historical", "historical"]
    assert sources[2] == "live_schwab"


@pytest.mark.asyncio
async def test_duplicate_ts_prefers_historical_in_merge() -> None:
    lf = datetime(2026, 5, 10, 16, 0, tzinfo=UTC)
    hist = [
        Bar(
            symbol="SPY",
            timestamp=lf,
            timeframe="1m",
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1,
            source="historical",
        )
    ]
    mh = _MockHistorical(lf, hist)
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    await live.set_live_bar(
        Bar(
            symbol="SPY",
            timestamp=lf,
            timeframe="1m",
            open=99,
            high=99,
            low=99,
            close=99,
            volume=9,
            source="live_schwab",
        )
    )
    settings = Settings(market_gateway_api_key="k", redis_url="redis://localhost:6379/0")
    r = DataResolver(settings, mh, live, StubSchwabClient())
    out = await r.get_bars(
        "SPY",
        "1m",
        start=lf - timedelta(minutes=1),
        end=lf + timedelta(minutes=1),
        mode=DataMode.CANONICAL_PLUS_LIVE,
    )
    at = [b for b in out.bars if b.timestamp == lf]
    assert len(at) == 1
    assert at[0].close == 10
