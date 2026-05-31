from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from market_gateway.app.config import Settings
from market_gateway.app.core.cache_keys import option_chain_key
from market_gateway.app.core.models import (
    DataMode,
    HistoricalDataResponse,
    OptionChainRequest,
    OptionChainResponse,
    OptionContractQuote,
    QuoteSnapshot,
)
from market_gateway.app.core.time_utils import ensure_utc, utc_now
from market_gateway.app.services.historical_store import (
    PostgresHistoricalStore,
    _deterministic_sample_bars,
    is_option_contract_symbol,
)
from market_gateway.schwab.normalize import schwab_candles_to_bars
from market_gateway.schwab.option_symbol import schwab_option_symbol

if TYPE_CHECKING:
    from market_gateway.app.services.historical_store import HistoricalStore
    from market_gateway.app.services.live_cache import LiveCache

log = logging.getLogger(__name__)


def merge_bars_by_preference(historical: list[Any], live: list[Any]) -> list[Any]:
    """Canonical historical wins on duplicate timestamps."""
    from market_gateway.app.core.models import Bar

    by_ts: dict[datetime, Bar] = {}
    for b in live:
        by_ts[ensure_utc(b.timestamp)] = b
    for b in historical:
        by_ts[ensure_utc(b.timestamp)] = b
    return sorted(by_ts.values(), key=lambda x: ensure_utc(x.timestamp))


class DataResolver:
    def __init__(
        self,
        settings: Settings,
        historical: HistoricalStore,
        live: LiveCache,
        schwab: Any,
    ) -> None:
        self._settings = settings
        self._historical = historical
        self._live = live
        self._schwab = schwab

    def _quote_source(self) -> str:
        return getattr(self._schwab, "quote_source_label", "sample")

    async def _live_bars_for_window(
        self,
        sym: str,
        timeframe: str,
        win_start: datetime,
        win_end: datetime,
    ) -> list[Any]:
        win_s = ensure_utc(win_start)
        win_e = ensure_utc(win_end)
        live = await self._live.get_live_bars(sym, timeframe, win_s, win_e)
        if live:
            return live
        if not self._settings.enable_schwab_live_data:
            return []
        if is_option_contract_symbol(sym):
            return []
        if timeframe not in ("1m", "1d"):
            return []
        # Pull a wider range than the live window; Schwab date filtering can be
        # exclusive or TZ-sensitive, then we filter to [win_s, win_e].
        fetch_start = win_s - timedelta(days=14)
        try:
            raw = await self._schwab.get_price_history(
                sym.upper(),
                timeframe,
                start=fetch_start,
                end=win_e,
                lookback_days=None,
            )
        except Exception as e:
            log.warning("Schwab price history failed for %s %s: %s", sym, timeframe, e)
            return []
        candles = raw.get("candles") if isinstance(raw, dict) else None
        if not isinstance(candles, list) or not candles:
            log.warning(
                "Schwab %s %s: no candles in response (empty=%s keys=%s) window=%s..%s fetch_start=%s",
                sym,
                timeframe,
                (raw.get("empty") if isinstance(raw, dict) else None),
                (list(raw.keys()) if isinstance(raw, dict) else None),
                win_s.isoformat(),
                win_e.isoformat(),
                fetch_start.isoformat(),
            )
            return []
        bars = schwab_candles_to_bars(sym, timeframe, candles)
        bars = [b for b in bars if win_s <= ensure_utc(b.timestamp) <= win_e]
        if not bars:
            log.warning(
                "Schwab %s %s: %d raw candles produced 0 bars in [%s, %s] after filter",
                sym,
                timeframe,
                len(candles),
                win_s.isoformat(),
                win_e.isoformat(),
            )
            return []
        by_day: dict[date, list[Any]] = defaultdict(list)
        for b in bars:
            by_day[ensure_utc(b.timestamp).date()].append(b)
        for day0, day_bars in by_day.items():
            await self._live.set_live_bars_day(
                sym, timeframe, day0, day_bars, self._settings.history_ttl_seconds
            )
        out = await self._live.get_live_bars(sym, timeframe, win_s, win_e)
        if not out:
            log.warning(
                "Schwab %s %s: wrote %d bars but Redis read returned empty for window %s..%s",
                sym,
                timeframe,
                len(bars),
                win_s.isoformat(),
                win_e.isoformat(),
            )
        return out

    def _parse_event_ts(self, raw: Any) -> datetime | None:
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return ensure_utc(raw)
        try:
            return ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except ValueError:
            return None

    def _append_sample_tail_when_live_empty(
        self,
        merged: list[Any],
        sym: str,
        timeframe: str,
        mode: DataMode,
        live: list[Any],
        live_start: datetime,
        end_u: datetime,
    ) -> list[Any]:
        """After Postgres canonical data, fill missing tail with sample bars if Redis live is empty."""
        if mode not in (DataMode.CANONICAL_PLUS_LIVE, DataMode.BEST_AVAILABLE):
            return merged
        if not isinstance(self._historical, PostgresHistoricalStore):
            return merged
        if live:
            return merged
        if live_start > end_u:
            return merged
        if (
            self._settings.enable_schwab_live_data
            and self._quote_source() == "live_schwab"
        ):
            log.warning(
                "Skipping deterministic sample tail for %s %s: live Schwab client active "
                "but no live bars in [%s, %s]. Schwab price history returned empty — "
                "check Market Data subscriptions in the Schwab developer portal, and that "
                "canonical DB dates are not ahead of real market history.",
                sym,
                timeframe,
                live_start.isoformat(),
                end_u.isoformat(),
            )
            return merged
        sym_key = sym if is_option_contract_symbol(sym) else sym.upper()
        sample_tail = _deterministic_sample_bars(
            sym_key, timeframe, live_start, end_u, source="sample"
        )
        if not sample_tail:
            return merged
        return merge_bars_by_preference(sample_tail, merged)

    async def get_quote(self, symbol: str) -> QuoteSnapshot:
        sym = symbol.upper()
        cached = await self._live.get_quote(sym)
        if cached:
            return cached

        raw = await self._schwab.get_quotes([sym])
        q = (raw.get("quotes") or {}).get(sym) or {}

        now = utc_now()
        snap = QuoteSnapshot(
            symbol=sym,
            event_ts=self._parse_event_ts(q.get("quoteTime")),
            received_ts=now,
            bid=q.get("bid"),
            ask=q.get("ask"),
            bid_size=q.get("bidSize"),
            ask_size=q.get("askSize"),
            last=q.get("last"),
            mark=q.get("mark"),
            volume=q.get("totalVolume"),
            source=self._quote_source(),
            raw=q or None,
        )
        await self._live.set_quote(snap, self._settings.quote_ttl_seconds)
        return snap

    async def get_option_quote(self, option_symbol: str) -> OptionContractQuote:
        osi = schwab_option_symbol(option_symbol)
        cached = await self._live.get_option_quote(osi)
        if cached:
            return cached

        raw = await self._schwab.get_option_quotes([osi])
        quotes = raw.get("quotes") or {}
        q = quotes.get(osi) or quotes.get(option_symbol.strip()) or {}
        now = utc_now()
        oc = OptionContractQuote(
            option_symbol=osi,
            underlying_symbol=None,
            expiration=None,
            strike=None,
            option_type=None,
            event_ts=self._parse_event_ts(q.get("quoteTime")),
            received_ts=now,
            bid=q.get("bid"),
            ask=q.get("ask"),
            last=q.get("last"),
            mark=q.get("mark"),
            delta=q.get("delta"),
            source=self._quote_source(),
            raw=q or None,
        )
        await self._live.set_option_quote(oc, self._settings.option_quote_ttl_seconds)
        return oc

    async def get_option_chain(self, request: OptionChainRequest) -> OptionChainResponse:
        key = option_chain_key(request)
        cached = await self._live.get_option_chain(key)
        if cached:
            return cached

        raw = await self._schwab.get_option_chain(
            request.symbol,
            contract_type=request.contract_type,
            expiration=request.expiration,
            from_date=request.from_date,
            to_date=request.to_date,
            strike_count=request.strike_count,
            include_quotes=request.include_quotes,
        )
        now = utc_now()
        contracts: list[OptionContractQuote] = []
        for c in raw.get("contracts") or []:
            exp_raw = c.get("expiration")
            exp: date | None = None
            if exp_raw:
                try:
                    exp = date.fromisoformat(str(exp_raw)[:10])
                except ValueError:
                    exp = None
            contracts.append(
                OptionContractQuote(
                    option_symbol=str(c.get("symbol", "")),
                    underlying_symbol=c.get("underlying"),
                    expiration=exp,
                    strike=float(c["strike"]) if c.get("strike") is not None else None,
                    option_type=c.get("contractType"),
                    event_ts=None,
                    received_ts=now,
                    bid=c.get("bid"),
                    ask=c.get("ask"),
                    last=c.get("last"),
                    mark=c.get("mark"),
                    delta=c.get("delta"),
                    source=self._quote_source(),
                    raw=c,
                )
            )
        resp = OptionChainResponse(
            symbol=request.symbol.upper(),
            underlying_price=raw.get("underlyingPrice"),
            requested_at=self._parse_event_ts(raw.get("requestedAt")) or now,
            received_ts=now,
            source=self._quote_source(),
            contracts=contracts,
        )
        await self._live.set_option_chain(key, resp, self._settings.option_chain_ttl_seconds)
        return resp

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        lookback_days: int | None = None,
        mode: DataMode = DataMode.CANONICAL_PLUS_LIVE,
    ) -> HistoricalDataResponse:
        now = utc_now()
        end_u = ensure_utc(end or now)
        if start is not None:
            start_u = ensure_utc(start)
        elif lookback_days is not None:
            start_u = end_u - timedelta(days=lookback_days)
        else:
            start_u = end_u - timedelta(days=7)

        sym = symbol

        if mode == DataMode.HISTORICAL_ONLY:
            if is_option_contract_symbol(sym):
                bars = await self._historical.get_option_bars(sym, timeframe, start_u, end_u)
            else:
                bars = await self._historical.get_equity_bars(sym.upper(), timeframe, start_u, end_u)
            return HistoricalDataResponse(
                symbol=sym,
                timeframe=timeframe,
                mode=mode.value,
                start=start_u,
                end=end_u,
                bars=bars,
            )

        if mode == DataMode.LIVE_ONLY:
            live = await self._live_bars_for_window(sym, timeframe, start_u, end_u)
            return HistoricalDataResponse(
                symbol=sym,
                timeframe=timeframe,
                mode=mode.value,
                start=start_u,
                end=end_u,
                bars=live,
            )

        # canonical_plus_live and best_available
        lf = await self._historical.get_last_finalized_timestamp(
            sym if is_option_contract_symbol(sym) else sym.upper(),
            timeframe,
        )
        hist: list[Any] = []
        if lf is None:
            if is_option_contract_symbol(sym):
                hist = await self._historical.get_option_bars(sym, timeframe, start_u, end_u)
            else:
                hist = await self._historical.get_equity_bars(sym.upper(), timeframe, start_u, end_u)
            live = await self._live_bars_for_window(sym, timeframe, start_u, end_u)
            merged = merge_bars_by_preference(hist, live)
        else:
            lf_u = ensure_utc(lf)
            hist_end = min(end_u, lf_u)
            live_start = max(start_u, lf_u)
            # Daily canonical rows use one timestamp per session/day; start sample/live tail next UTC day.
            if timeframe == "1d" and not is_option_contract_symbol(sym):
                live_start = max(start_u, lf_u + timedelta(days=1))
            if start_u <= hist_end:
                if is_option_contract_symbol(sym):
                    hist = await self._historical.get_option_bars(
                        sym, timeframe, start_u, hist_end
                    )
                else:
                    hist = await self._historical.get_equity_bars(
                        sym.upper(), timeframe, start_u, hist_end
                    )
            live: list[Any] = []
            if live_start <= end_u:
                live = await self._live_bars_for_window(sym, timeframe, live_start, end_u)
            merged = merge_bars_by_preference(hist, live)
            merged = self._append_sample_tail_when_live_empty(
                merged, sym, timeframe, mode, live, live_start, end_u
            )

        return HistoricalDataResponse(
            symbol=sym,
            timeframe=timeframe,
            mode=mode.value,
            start=start_u,
            end=end_u,
            bars=merged,
        )
