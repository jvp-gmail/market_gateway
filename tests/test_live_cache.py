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


@pytest.mark.asyncio
async def test_live_bars_window_covered_1d_midnight_bar_covers_full_utc_day() -> None:
    """Daily bars sit at UTC midnight; need_hi is end-of-day, so span check must use overlap."""
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    d = date(2026, 8, 1)
    b = Bar(
        symbol="Z",
        timestamp=datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC),
        timeframe="1d",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        source="live_schwab",
    )
    await live.set_live_bars_day("Z", "1d", d, [b], ttl_seconds=3600)
    win_s = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    win_e = datetime(2026, 8, 1, 23, 59, 59, tzinfo=UTC)
    assert await live.live_bars_window_covered("Z", "1d", win_s, win_e)


@pytest.mark.asyncio
async def test_live_bars_window_covered_1d_subwindow_without_bar_not_satisfied() -> None:
    """1d overlap: window that excludes the lone midnight bar must not count as covered."""
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    d = date(2026, 8, 2)
    b = Bar(
        symbol="W",
        timestamp=datetime(2026, 8, 2, 0, 0, 0, tzinfo=UTC),
        timeframe="1d",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        source="live_schwab",
    )
    await live.set_live_bars_day("W", "1d", d, [b], ttl_seconds=3600)
    win_s = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
    win_e = datetime(2026, 8, 2, 18, 0, 0, tzinfo=UTC)
    assert not await live.live_bars_window_covered("W", "1d", win_s, win_e)


@pytest.mark.asyncio
async def test_merge_live_bars_day_unions_intraday_without_dropping_cached_tail() -> None:
    """Narrow Schwab slice must not replace a wider per-day blob; merge by timestamp."""
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    d = date(2026, 9, 1)
    full = [
        Bar(
            symbol="M",
            timestamp=datetime(2026, 9, 1, h, 0, tzinfo=UTC),
            timeframe="1m",
            open=1,
            high=1,
            low=1,
            close=float(h),
            volume=1,
            source="live_schwab",
        )
        for h in (10, 11, 15)
    ]
    narrow = [b for b in full if int(b.close) in (10, 11)]
    await live.set_live_bars_day("M", "1m", d, full, ttl_seconds=3600)
    await live.merge_live_bars_day("M", "1m", d, narrow, ttl_seconds=3600)
    got = await live.get_live_bars(
        "M",
        "1m",
        datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )
    assert [int(b.close) for b in got] == [10, 11, 15]


@pytest.mark.asyncio
async def test_merge_live_bars_day_incoming_wins_duplicate_timestamp() -> None:
    fake = FakeRedis(decode_responses=True)
    live = LiveCache(fake)
    d = date(2026, 9, 2)
    ts = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    old = Bar(
        symbol="M",
        timestamp=ts,
        timeframe="1m",
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
        source="live_schwab",
    )
    new = Bar(
        symbol="M",
        timestamp=ts,
        timeframe="1m",
        open=2,
        high=2,
        low=2,
        close=99,
        volume=2,
        source="live_schwab",
    )
    await live.set_live_bars_day("M", "1m", d, [old], ttl_seconds=3600)
    await live.merge_live_bars_day("M", "1m", d, [new], ttl_seconds=3600)
    got = await live.get_live_bars("M", "1m", ts, ts)
    assert len(got) == 1
    assert got[0].close == 99
