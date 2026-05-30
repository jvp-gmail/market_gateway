from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

BarSource = Literal["historical", "live_schwab", "sample", "derived"]

import asyncpg

from market_gateway.app.core.models import Bar
from market_gateway.app.core.time_utils import ensure_utc

log = logging.getLogger(__name__)

# Backtester4 canonical tables (see Backtester4 docs / cache).
EQUITY_TABLE_1M = "stocks_1_minute"
EQUITY_TABLE_1D = "stocks_1_day"
OPTION_TABLE_1M = "options_1_minute"


def _asyncpg_dsn(database_url: str) -> str:
    u = database_url.strip()
    if "+asyncpg" in u:
        u = u.replace("postgresql+asyncpg://", "postgresql://", 1)
    return u


def _day_table_row_to_bar(
    symbol: str,
    timeframe: str,
    row: dict[str, Any],
    *,
    source: BarSource,
) -> Bar | None:
    """Build a Bar from stocks_1_day (column `date`, not timestamptz `time`)."""
    d = row.get("date")
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    if not isinstance(d, date):
        return None
    ts = datetime.combine(d, time.min, tzinfo=UTC)
    return Bar(
        symbol=symbol,
        timestamp=ts,
        timeframe=timeframe,
        open=float(row.get("open") or row.get("close") or 0),
        high=float(row.get("high") or row.get("close") or 0),
        low=float(row.get("low") or row.get("close") or 0),
        close=float(row.get("close") or 0),
        volume=int(row.get("volume") or 0),
        source=source,
    )


def is_option_contract_symbol(symbol: str) -> bool:
    """Heuristic: OCC-style option symbols contain an underscore."""
    return "_" in symbol


def _row_to_bar(
    symbol: str,
    timeframe: str,
    row: dict[str, Any],
    *,
    source: BarSource,
) -> Bar | None:
    t = row.get("time")
    if t is None:
        return None
    if hasattr(t, "tzinfo") and t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    else:
        t = ensure_utc(t)
    return Bar(
        symbol=symbol,
        timestamp=t,
        timeframe=timeframe,
        open=float(row.get("open") or row.get("close") or 0),
        high=float(row.get("high") or row.get("close") or 0),
        low=float(row.get("low") or row.get("close") or 0),
        close=float(row.get("close") or 0),
        volume=int(row.get("volume") or 0),
        source=source,
    )


class HistoricalStore(ABC):
    @abstractmethod
    async def get_equity_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...

    @abstractmethod
    async def get_option_bars(
        self,
        option_symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        ...

    @abstractmethod
    async def get_last_finalized_timestamp(
        self,
        symbol: str,
        timeframe: str,
    ) -> datetime | None:
        ...


class SampleHistoricalStore(HistoricalStore):
    """Deterministic intraday-ish sample bars when no database is configured."""

    async def get_equity_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        return _deterministic_sample_bars(symbol, timeframe, start, end, source="sample")

    async def get_option_bars(
        self,
        option_symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        return _deterministic_sample_bars(
            option_symbol, timeframe, start, end, source="sample"
        )

    async def get_last_finalized_timestamp(
        self,
        symbol: str,
        timeframe: str,
    ) -> datetime | None:
        _ = symbol, timeframe
        return None


class PostgresHistoricalStore(HistoricalStore):
    """Reads canonical equity bars from `stocks_1_minute` / `stocks_1_day` and options from `options_1_minute`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def close(self) -> None:
        await self._pool.close()

    async def ping(self) -> bool:
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def get_equity_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        start_u, end_u = ensure_utc(start), ensure_utc(end)
        if timeframe == "1m":
            q = f"""
                SELECT time, open, high, low, close, volume
                FROM {EQUITY_TABLE_1M}
                WHERE symbol = $1 AND time >= $2 AND time <= $3
                ORDER BY time ASC
            """
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(q, symbol.upper(), start_u, end_u)
            out: list[Bar] = []
            for row in rows:
                b = _row_to_bar(symbol.upper(), timeframe, dict(row), source="historical")
                if b:
                    out.append(b)
            return out
        if timeframe == "1d":
            start_d = start_u.astimezone(UTC).date()
            end_d = end_u.astimezone(UTC).date()
            q = f"""
                SELECT date, open, high, low, close, volume
                FROM {EQUITY_TABLE_1D}
                WHERE symbol = $1 AND date >= $2 AND date <= $3
                ORDER BY date ASC
            """
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(q, symbol.upper(), start_d, end_d)
            out: list[Bar] = []
            for row in rows:
                b = _day_table_row_to_bar(symbol.upper(), timeframe, dict(row), source="historical")
                if b:
                    out.append(b)
            return out
        log.info("unsupported equity timeframe %s — returning empty", timeframe)
        return []

    async def get_option_bars(
        self,
        option_symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        if timeframe != "1m":
            return []
        start_u, end_u = ensure_utc(start), ensure_utc(end)
        q = f"""
            SELECT time, open, high, low, close, volume
            FROM {OPTION_TABLE_1M}
            WHERE option_symbol = $1 AND time >= $2 AND time <= $3
            ORDER BY time ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q, option_symbol, start_u, end_u)
        out: list[Bar] = []
        for row in rows:
            b = _row_to_bar(option_symbol, timeframe, dict(row), source="historical")
            if b:
                out.append(b)
        return out

    async def get_last_finalized_timestamp(
        self,
        symbol: str,
        timeframe: str,
    ) -> datetime | None:
        if is_option_contract_symbol(symbol):
            if timeframe != "1m":
                return None
            q = f"SELECT max(time) AS m FROM {OPTION_TABLE_1M} WHERE option_symbol = $1"
            key = symbol
        elif timeframe == "1m":
            q = f"SELECT max(time) AS m FROM {EQUITY_TABLE_1M} WHERE symbol = $1"
            key = symbol.upper()
        elif timeframe == "1d":
            q = f"SELECT max(date) AS m FROM {EQUITY_TABLE_1D} WHERE symbol = $1"
            key = symbol.upper()
        else:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(q, key)
        if not row or row["m"] is None:
            return None
        t = row["m"]
        if type(t) is date:
            return datetime.combine(t, time.min, tzinfo=UTC)
        return ensure_utc(t) if hasattr(t, "tzinfo") else t.replace(tzinfo=UTC)


def _deterministic_sample_bars(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    source: BarSource,
) -> list[Bar]:
    """Synthetic OHLCV for gaps / dev. Daily bars use UTC midnight timestamps."""
    start_u, end_u = ensure_utc(start), ensure_utc(end)
    if end_u < start_u:
        return []
    seed = int(hashlib.sha256(f"{symbol}:{timeframe}".encode()).hexdigest()[:8], 16)
    base = 100.0 + (seed % 5000) / 100.0
    bars: list[Bar] = []
    if timeframe == "1d":
        cur = start_u.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        end_day = end_u.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        i = 0
        while cur <= end_day:
            o = base + (i % 7) * 0.05
            h = o + 0.12
            l = o - 0.08
            c = o + 0.03
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=cur,
                    timeframe=timeframe,
                    open=round(o, 4),
                    high=round(h, 4),
                    low=round(l, 4),
                    close=round(c, 4),
                    volume=1_000_000 + i * 50_000,
                    source=source,
                )
            )
            cur += timedelta(days=1)
            i += 1
        return bars

    cur = start_u.replace(minute=0, second=0, microsecond=0)
    i = 0
    while cur <= end_u:
        o = base + (i % 7) * 0.05
        h = o + 0.12
        l = o - 0.08
        c = o + 0.03
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=cur,
                timeframe=timeframe,
                open=round(o, 4),
                high=round(h, 4),
                low=round(l, 4),
                close=round(c, 4),
                volume=1000 + i * 10,
                source=source,
            )
        )
        cur += timedelta(hours=1)
        i += 1
    return bars


async def create_historical_store(database_url: str | None) -> HistoricalStore:
    if not database_url:
        return SampleHistoricalStore()
    pool = await asyncpg.create_pool(_asyncpg_dsn(database_url), min_size=1, max_size=5)
    return PostgresHistoricalStore(pool)
