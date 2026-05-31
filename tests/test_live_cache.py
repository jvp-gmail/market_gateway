"""Tests for ``LiveCache``."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fakeredis.aioredis import FakeRedis

from market_gateway.app.core.models import Bar
from market_gateway.app.services.live_cache import LiveCache


@pytest.mark.asyncio
async def test_live_bars_window_covered_uses_bar_timestamps_not_stale_cov() -> None:
    """Wide merged cov + narrow bar blob must not satisfy an earlier sub-window."""
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    d = date(2026, 7, 1)
    b = Bar(
        symbol="X",
        timestamp=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
        timeframe="1m",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        source="live_schwab",
    )
    await live.set_live_bars_day("X", "1m", d, [b], ttl_seconds=3600)
    await live.merge_live_bars_window_coverage(
        "X",
        "1m",
        d,
        datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 7, 1, 16, 0, tzinfo=UTC),
        ttl_seconds=3600,
    )
    win_s = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    win_e = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)
    assert not await live.live_bars_window_covered("X", "1m", win_s, win_e)


@pytest.mark.asyncio
async def test_live_bars_window_covered_true_when_blob_spans_window() -> None:
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    d = date(2026, 7, 2)
    bars = [
        Bar(
            symbol="Y",
            timestamp=datetime(2026, 7, 2, h, 0, tzinfo=UTC),
            timeframe="1m",
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
            source="live_schwab",
        )
        for h in (10, 11, 14)
    ]
    await live.set_live_bars_day("Y", "1m", d, bars, ttl_seconds=3600)
    win_s = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    win_e = datetime(2026, 7, 2, 14, 0, tzinfo=UTC)
    assert await live.live_bars_window_covered("Y", "1m", win_s, win_e)
