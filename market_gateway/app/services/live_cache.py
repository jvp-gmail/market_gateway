from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from market_gateway.app.core.cache_keys import (
    history_live_key,
    option_chain_key,
    option_quote_key,
    quote_key,
)
from market_gateway.app.core.models import Bar, OptionChainResponse, OptionContractQuote, QuoteSnapshot
from market_gateway.app.core.time_utils import ensure_utc, utc_now

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = logging.getLogger(__name__)


def _model_json(model: Any) -> str:
    return model.model_dump_json()


def _parse_quote(raw: str | None) -> QuoteSnapshot | None:
    if not raw:
        return None
    return QuoteSnapshot.model_validate_json(raw)


def _parse_option_quote(raw: str | None) -> OptionContractQuote | None:
    if not raw:
        return None
    return OptionContractQuote.model_validate_json(raw)


def _parse_chain(raw: str | None) -> OptionChainResponse | None:
    if not raw:
        return None
    return OptionChainResponse.model_validate_json(raw)


class LiveCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_quote(self, symbol: str) -> QuoteSnapshot | None:
        raw = await self._redis.get(quote_key(symbol))
        return _parse_quote(raw)

    async def set_quote(self, quote: QuoteSnapshot, ttl_seconds: int) -> None:
        await self._redis.set(quote_key(quote.symbol), _model_json(quote), ex=ttl_seconds)

    async def get_option_quote(self, option_symbol: str) -> OptionContractQuote | None:
        raw = await self._redis.get(option_quote_key(option_symbol))
        return _parse_option_quote(raw)

    async def set_option_quote(self, quote: OptionContractQuote, ttl_seconds: int) -> None:
        await self._redis.set(
            option_quote_key(quote.option_symbol),
            _model_json(quote),
            ex=ttl_seconds,
        )

    async def get_option_chain(self, cache_key: str) -> OptionChainResponse | None:
        raw = await self._redis.get(cache_key)
        return _parse_chain(raw)

    async def set_option_chain(
        self, cache_key: str, chain: OptionChainResponse, ttl_seconds: int
    ) -> None:
        await self._redis.set(cache_key, _model_json(chain), ex=ttl_seconds)

    async def get_live_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        start_u = ensure_utc(start)
        end_u = ensure_utc(end)
        bars: list[Bar] = []
        day = start_u.date()
        end_day = end_u.date()
        while day <= end_day:
            key = history_live_key(symbol, timeframe, day.isoformat())
            raw = await self._redis.get(key)
            if raw:
                try:
                    chunk = json.loads(raw)
                    for b in chunk:
                        bar = Bar.model_validate(b)
                        ts = ensure_utc(bar.timestamp)
                        if start_u <= ts <= end_u:
                            bars.append(bar)
                except (json.JSONDecodeError, ValueError) as e:
                    log.warning("bad history_live payload for %s: %s", key, e)
            day += timedelta(days=1)
        bars.sort(key=lambda b: b.timestamp)
        return bars

    async def set_live_bars_day(
        self, symbol: str, timeframe: str, day: date, bars: list[Bar], ttl_seconds: int
    ) -> None:
        key = history_live_key(symbol, timeframe, day.isoformat())
        payload = json.dumps([b.model_dump(mode="json") for b in bars], default=str)
        await self._redis.set(key, payload, ex=ttl_seconds)

    async def set_live_bar(self, bar: Bar, ttl_seconds: int = 86400) -> None:
        """Upsert one bar into the per-day Redis blob for live/session bars."""
        ts = ensure_utc(bar.timestamp)
        day = ts.date()
        key = history_live_key(bar.symbol, bar.timeframe, day.isoformat())
        raw = await self._redis.get(key)
        bars: list[Bar] = []
        if raw:
            try:
                bars = [Bar.model_validate(x) for x in json.loads(raw)]
            except (json.JSONDecodeError, ValueError):
                bars = []
        bars = [b for b in bars if ensure_utc(b.timestamp) != ts]
        bars.append(bar)
        bars.sort(key=lambda b: ensure_utc(b.timestamp))
        await self._redis.set(
            key,
            json.dumps([b.model_dump(mode="json") for b in bars], default=str),
            ex=ttl_seconds,
        )
