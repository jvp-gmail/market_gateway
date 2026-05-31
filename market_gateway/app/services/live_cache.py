from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from redis.asyncio.client import Pipeline

from market_gateway.app.core.cache_keys import (
    history_live_backfill_miss_key,
    history_live_cov_key,
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

    def _utc_day_start(self, d: date) -> datetime:
        return datetime.combine(d, time.min, tzinfo=UTC)

    def _utc_day_bar_ts_envelope(
        self, bar_list: list[Any], day_start: datetime, day_end_excl: datetime
    ) -> tuple[datetime, datetime] | None:
        """Min/max bar timestamps within [day_start, day_end_excl). None if no usable bars."""
        lo: datetime | None = None
        hi: datetime | None = None
        for b in bar_list:
            try:
                bar = Bar.model_validate(b)
            except ValueError:
                return None
            ts = ensure_utc(bar.timestamp)
            if ts < day_start or ts >= day_end_excl:
                continue
            if lo is None or ts < lo:
                lo = ts
            if hi is None or ts > hi:
                hi = ts
        if lo is None or hi is None:
            return None
        return (lo, hi)

    def _bar_list_has_ts_in_closed_range(
        self,
        bar_list: list[Any],
        day_start: datetime,
        day_end_excl: datetime,
        need_lo: datetime,
        need_hi: datetime,
    ) -> bool:
        for b in bar_list:
            try:
                bar = Bar.model_validate(b)
            except ValueError:
                continue
            ts = ensure_utc(bar.timestamp)
            if ts < day_start or ts >= day_end_excl:
                continue
            if need_lo <= ts <= need_hi:
                return True
        return False

    async def live_bars_window_covered(
        self,
        symbol: str,
        timeframe: str,
        win_s: datetime,
        win_e: datetime,
    ) -> bool:
        """True if each touched UTC day's cached bars span that day's slice of [win_s, win_e].

        Uses min/max bar timestamps in the per-day Redis blob. ``history_live_cov`` is not
        consulted: it can remain wider than the blob after partial writes.
        """
        start_u = ensure_utc(win_s)
        end_u = ensure_utc(win_e)
        d = start_u.date()
        end_day = end_u.date()
        while d <= end_day:
            day_start = self._utc_day_start(d)
            day_end_excl = day_start + timedelta(days=1)
            if end_u < day_start or start_u >= day_end_excl:
                d += timedelta(days=1)
                continue
            need_lo = max(start_u, day_start)
            need_hi = min(end_u, day_end_excl - timedelta(microseconds=1))
            if need_lo > need_hi:
                d += timedelta(days=1)
                continue
            day_iso = d.isoformat()
            bars_key = history_live_key(symbol, timeframe, day_iso)
            raw_bars = await self._redis.get(bars_key)
            if raw_bars is None:
                return False
            try:
                bar_list = json.loads(raw_bars)
            except (json.JSONDecodeError, TypeError):
                return False
            if not isinstance(bar_list, list) or len(bar_list) == 0:
                return False
            env = self._utc_day_bar_ts_envelope(bar_list, day_start, day_end_excl)
            if env is None:
                return False
            bar_lo, bar_hi = env
            # Intraday: min/max must bracket the slice, and at least one bar must fall inside
            # [need_lo, need_hi]. Otherwise sparse bars (e.g. only session open/close) can make
            # the envelope span the window while get_live_bars returns nothing for that slice.
            if timeframe == "1d":
                # Daily bars use UTC midnight per calendar day, so bar_hi is usually far before
                # end-of-day; require interval overlap with [need_lo, need_hi], then at least one
                # bar timestamp in that slice (envelope alone can span the slice without a bar in it).
                if bar_hi < need_lo or bar_lo > need_hi:
                    return False
                if not self._bar_list_has_ts_in_closed_range(
                    bar_list, day_start, day_end_excl, need_lo, need_hi
                ):
                    return False
            else:
                if bar_lo > need_lo or bar_hi < need_hi:
                    return False
                if not self._bar_list_has_ts_in_closed_range(
                    bar_list, day_start, day_end_excl, need_lo, need_hi
                ):
                    return False
            d += timedelta(days=1)
        return True

    async def live_backfill_miss_active(
        self, symbol: str, timeframe: str, win_s: datetime, win_e: datetime
    ) -> bool:
        key = history_live_backfill_miss_key(symbol, timeframe, win_s, win_e)
        return await self._redis.get(key) is not None

    async def set_live_backfill_miss(
        self,
        symbol: str,
        timeframe: str,
        win_s: datetime,
        win_e: datetime,
        ttl_seconds: int,
    ) -> None:
        key = history_live_backfill_miss_key(symbol, timeframe, win_s, win_e)
        await self._redis.set(key, "1", ex=max(1, ttl_seconds))

    async def clear_live_backfill_miss(
        self, symbol: str, timeframe: str, win_s: datetime, win_e: datetime
    ) -> None:
        key = history_live_backfill_miss_key(symbol, timeframe, win_s, win_e)
        await self._redis.delete(key)

    async def merge_live_bars_window_coverage(
        self,
        symbol: str,
        timeframe: str,
        day: date,
        win_s: datetime,
        win_e: datetime,
        ttl_seconds: int,
    ) -> None:
        """Expand stored coverage union for this day to include [win_s, win_e]."""
        key = history_live_cov_key(symbol, timeframe, day.isoformat())
        ws = ensure_utc(win_s)
        we = ensure_utc(win_e)
        raw = await self._redis.get(key)
        if raw:
            try:
                prev = json.loads(raw)
                lo = ensure_utc(
                    datetime.fromisoformat(str(prev["lo"]).replace("Z", "+00:00"))
                )
                hi = ensure_utc(
                    datetime.fromisoformat(str(prev["hi"]).replace("Z", "+00:00"))
                )
                lo = min(lo, ws)
                hi = max(hi, we)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                lo, hi = ws, we
        else:
            lo, hi = ws, we
        payload = json.dumps({"lo": lo.isoformat(), "hi": hi.isoformat()})
        await self._redis.set(key, payload, ex=ttl_seconds)

    async def set_live_bars_day(
        self, symbol: str, timeframe: str, day: date, bars: list[Bar], ttl_seconds: int
    ) -> None:
        key = history_live_key(symbol, timeframe, day.isoformat())
        payload = json.dumps([b.model_dump(mode="json") for b in bars], default=str)
        await self._redis.set(key, payload, ex=ttl_seconds)

    def _merged_live_bars_day_payload(
        self,
        raw: str | None,
        day_start: datetime,
        day_end_excl: datetime,
        bars: list[Bar],
    ) -> str:
        existing: list[Bar] = []
        if raw:
            try:
                existing = [Bar.model_validate(x) for x in json.loads(raw)]
            except (json.JSONDecodeError, ValueError):
                existing = []
        existing = [
            b
            for b in existing
            if day_start <= ensure_utc(b.timestamp) < day_end_excl
        ]
        by_ts: dict[datetime, Bar] = {ensure_utc(b.timestamp): b for b in existing}
        for b in bars:
            ts = ensure_utc(b.timestamp)
            if day_start <= ts < day_end_excl:
                by_ts[ts] = b
        merged = sorted(by_ts.values(), key=lambda b: ensure_utc(b.timestamp))
        return json.dumps([b.model_dump(mode="json") for b in merged], default=str)

    async def merge_live_bars_day(
        self, symbol: str, timeframe: str, day: date, bars: list[Bar], ttl_seconds: int
    ) -> None:
        """Union per-day Redis bars with ``bars``; incoming wins on duplicate UTC timestamps.

        Schwab history is requested with ``end`` at the current window; without merging, a
        narrower ``win_e`` would replace the blob with only candles through that instant and
        drop later intraday bars already cached from a wider fetch.

        The merge is applied inside a Redis optimistic transaction (``WATCH`` / ``MULTI`` /
        ``EXEC``) so concurrent backfills or ``/history`` paths for the same key cannot drop
        each other's bars: if the blob changes between read and write, the transaction aborts
        and retries with fresh state.
        """
        key = history_live_key(symbol, timeframe, day.isoformat())
        day_start = self._utc_day_start(day)
        day_end_excl = day_start + timedelta(days=1)

        async def _merge_tx(pipe: Pipeline) -> None:
            raw_tx = await pipe.get(key)
            payload = self._merged_live_bars_day_payload(
                raw_tx, day_start, day_end_excl, bars
            )
            pipe.multi()
            pipe.set(key, payload, ex=ttl_seconds)

        await self._redis.transaction(_merge_tx, key)

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
