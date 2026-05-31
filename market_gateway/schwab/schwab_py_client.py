"""Async Schwab Trader API client via schwab-py (Phase 3 read-only market data)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime, time as time_of_day, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import httpx

from market_gateway.app.config import Settings
from market_gateway.app.core.time_utils import ensure_utc
from market_gateway.schwab.errors import SchwabHttpError
from market_gateway.schwab.normalize import (
    flatten_option_chain,
    normalize_quotes_response,
)

if TYPE_CHECKING:
    from schwab.client.asynchronous import AsyncClient

from schwab.client.base import BaseClient

log = logging.getLogger(__name__)

# Schwab daily history expects session-style bounds; match batch updaters that use ET
# calendar days (see schwab_daily_stock_updater.py: combine(date, min/max, TZ_ET)).
TZ_ET = ZoneInfo("America/New_York")
_DAILY_HISTORY_CHUNK_DAYS = 365


class _AsyncRateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._min = max(0.0, min_interval_seconds)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        if self._min <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self._min - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class SchwabPyMarketClient:
    """Thin async wrapper: rate limiting, HTTP checks, normalized payloads."""

    @property
    def quote_source_label(self) -> str:
        return "live_schwab"

    def __init__(self, inner: AsyncClient, settings: Settings) -> None:
        self._inner = inner
        self._settings = settings
        self._limiter = _AsyncRateLimiter(settings.schwab_min_request_interval_seconds)

    async def aclose(self) -> None:
        await self._inner.close_async_session()

    def _parse_json(self, resp: httpx.Response, *, what: str) -> Any:
        if resp.status_code >= 400:
            body = resp.text[:500] if resp.text else ""
            raise SchwabHttpError(
                f"Schwab {what} failed: HTTP {resp.status_code} {body}",
                status_code=resp.status_code,
            )
        return resp.json()

    async def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        await self._limiter.acquire()
        syms = [s.strip().upper() for s in symbols if s.strip()]
        if not syms:
            return {"quotes": {}}
        resp = await self._inner.get_quotes(syms)
        data = self._parse_json(resp, what="get_quotes")
        if not isinstance(data, dict):
            return {"quotes": {}}
        return normalize_quotes_response(data, syms)

    async def get_option_chain(
        self,
        symbol: str,
        contract_type: str = "ALL",
        expiration: date | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        strike_count: int | None = None,
        include_quotes: bool = True,
        **_extra: Any,
    ) -> dict[str, Any]:
        await self._limiter.acquire()
        u = symbol.strip().upper()
        try:
            ct_enum = BaseClient.Options.ContractType[contract_type]
        except KeyError:
            ct_enum = BaseClient.Options.ContractType.ALL

        fd = from_date
        td = to_date
        if expiration is not None:
            fd = expiration
            td = expiration

        resp = await self._inner.get_option_chain(
            u,
            contract_type=ct_enum,
            strike_count=strike_count,
            include_underlying_quote=True,
            from_date=fd,
            to_date=td,
        )
        raw = self._parse_json(resp, what="get_option_chain")
        if not isinstance(raw, dict):
            return flatten_option_chain({}, underlying=u)
        flat = flatten_option_chain(raw, underlying=u)
        flat["includeQuotes"] = include_quotes
        return flat

    async def get_option_quotes(self, option_symbols: list[str]) -> dict[str, Any]:
        return await self.get_quotes(option_symbols)

    async def _get_price_history_1d(
        self,
        sym: str,
        start_u: datetime,
        end_u: datetime,
    ) -> dict[str, Any]:
        """Daily bars: prefer get_price_history_every_day with ET bounds (Schwab batch updater pattern)."""
        start_date_et = start_u.astimezone(TZ_ET).date()
        end_date_et = end_u.astimezone(TZ_ET).date()
        if start_date_et > end_date_et:
            start_date_et = end_date_et

        candles: list[Any] = []
        seen_ms: set[int] = set()
        raw: dict[str, Any] = {}
        last_resp: httpx.Response | None = None

        chunk_start = start_date_et
        while chunk_start <= end_date_et:
            chunk_end = min(
                chunk_start + timedelta(days=_DAILY_HISTORY_CHUNK_DAYS - 1),
                end_date_et,
            )
            start_dt_et = datetime.combine(chunk_start, time_of_day.min, tzinfo=TZ_ET)
            end_dt_et = datetime.combine(chunk_end, time_of_day.max, tzinfo=TZ_ET)
            await self._limiter.acquire()
            resp = await self._inner.get_price_history_every_day(
                sym,
                start_datetime=start_dt_et,
                end_datetime=end_dt_et,
                need_extended_hours_data=False,
            )
            last_resp = resp
            body = self._parse_json(resp, what="get_price_history_every_day(1d)")
            if isinstance(body, dict):
                raw = body
                cdt = body.get("candles")
            else:
                cdt = None
            if isinstance(cdt, list):
                for c in cdt:
                    if not isinstance(c, dict):
                        continue
                    ts = c.get("datetime")
                    if isinstance(ts, (int, float)):
                        k = int(ts)
                        if k in seen_ms:
                            continue
                        seen_ms.add(k)
                    candles.append(c)
            chunk_start = chunk_end + timedelta(days=1)

        if candles:
            log.info("Schwab 1d pricehistory ok via every_day_et (%d candles)", len(candles))
        else:
            # Fallback: period-based get_price_history (UTC bounds) when every_day returns empty.
            ph = BaseClient.PriceHistory
            strategies: list[tuple[str, dict[str, Any]]] = [
                (
                    "month_1_no_dates",
                    {
                        "period_type": ph.PeriodType.MONTH,
                        "period": ph.Period.ONE_MONTH,
                        "frequency_type": ph.FrequencyType.DAILY,
                        "frequency": ph.Frequency.EVERY_MINUTE,
                        "need_extended_hours_data": False,
                    },
                ),
                (
                    "ytd_open",
                    {
                        "period_type": ph.PeriodType.YEAR_TO_DATE,
                        "period": ph.Period.YEAR_TO_DATE,
                        "frequency_type": ph.FrequencyType.DAILY,
                        "frequency": ph.Frequency.EVERY_MINUTE,
                        "need_extended_hours_data": False,
                    },
                ),
                (
                    "year_1y_no_dates",
                    {
                        "period_type": ph.PeriodType.YEAR,
                        "period": ph.Period.ONE_YEAR,
                        "frequency_type": ph.FrequencyType.DAILY,
                        "frequency": ph.Frequency.EVERY_MINUTE,
                        "need_extended_hours_data": False,
                    },
                ),
                (
                    "month_6m_bounded",
                    {
                        "period_type": ph.PeriodType.MONTH,
                        "period": ph.Period.SIX_MONTHS,
                        "frequency_type": ph.FrequencyType.DAILY,
                        "frequency": ph.Frequency.EVERY_MINUTE,
                        "start_datetime": start_u,
                        "end_datetime": end_u,
                        "need_extended_hours_data": False,
                    },
                ),
            ]
            for label, kw in strategies:
                await self._limiter.acquire()
                resp = await self._inner.get_price_history(sym, **kw)
                last_resp = resp
                body = self._parse_json(resp, what=f"get_price_history(1d/{label})")
                if not isinstance(body, dict):
                    continue
                raw = body
                cdt = body.get("candles")
                if isinstance(cdt, list) and len(cdt) > 0:
                    candles = cdt
                    log.info(
                        "Schwab 1d pricehistory ok via %s (%d candles, empty=%s)",
                        label,
                        len(cdt),
                        body.get("empty"),
                    )
                    break

        if not candles and last_resp is not None:
            snippet = getattr(last_resp, "text", "") or ""
            log.warning(
                "Schwab pricehistory returned no candles for %s 1d after every_day_et + fallbacks; "
                "last empty=%s keys=%s body=%s — if quotes work but history is empty, "
                "your app likely lacks Market Data API access for historical bars.",
                sym,
                raw.get("empty") if isinstance(raw, dict) else None,
                list(raw.keys()) if isinstance(raw, dict) else None,
                snippet[:800],
            )

        return {
            "symbol": sym,
            "timeframe": "1d",
            "start": start_u.isoformat(),
            "end": end_u.isoformat(),
            "candles": candles if isinstance(candles, list) else [],
        }

    async def get_price_history(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        lookback_days: int | None = None,
    ) -> dict[str, Any]:
        sym = symbol.strip().upper()
        tf = timeframe.strip().lower()
        now = datetime.now(UTC)
        end_u = ensure_utc(end or now)
        if start is None and lookback_days is not None:
            start_u = end_u - timedelta(days=lookback_days)
        elif start is not None:
            start_u = ensure_utc(start)
        else:
            start_u = end_u - timedelta(days=1)

        if tf == "1d":
            return await self._get_price_history_1d(sym, start_u, end_u)

        await self._limiter.acquire()
        if tf == "1m":
            resp = await self._inner.get_price_history_every_minute(
                sym,
                start_datetime=start_u,
                end_datetime=end_u,
            )
            raw = self._parse_json(resp, what="get_price_history(1m)")
            candles = raw.get("candles") if isinstance(raw, dict) else None
            if not isinstance(candles, list):
                candles = []
            if not candles and isinstance(raw, dict):
                snippet = getattr(resp, "text", "") or ""
                log.warning(
                    "Schwab pricehistory returned no candles for %s 1m keys=%s body=%s",
                    sym,
                    list(raw.keys()),
                    snippet[:800],
                )
            return {
                "symbol": sym,
                "timeframe": tf,
                "start": start_u.isoformat(),
                "end": end_u.isoformat(),
                "candles": candles,
            }

        log.info("Schwab price history not requested for unsupported timeframe %s", tf)
        return {
            "symbol": sym,
            "timeframe": tf,
            "start": start_u.isoformat(),
            "end": end_u.isoformat(),
            "candles": [],
        }

    async def get_positions(self) -> dict[str, Any]:
        """Phase 3 keeps positions read path unimplemented; return empty (no account wiring)."""
        return {"positions": []}

    async def preview_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Paper/stub semantics until Phase 5+ broker preview."""
        return {"ok": True, "estimatedNotional": order.get("quantity", 1) * 150.0}

    async def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Paper/stub semantics; live Schwab order submission is out of scope for Phase 3."""
        return {"ok": True, "orderId": "stub-order", "raw": order}
