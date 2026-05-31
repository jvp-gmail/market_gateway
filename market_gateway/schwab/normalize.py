"""Map Schwab Trader API JSON into gateway-friendly dicts (quotes, chains, candles)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from market_gateway.app.core.models import Bar

log = logging.getLogger(__name__)

_NY = ZoneInfo("America/New_York")


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_ref_expiration(ref: dict[str, Any]) -> date | None:
    exp = ref.get("expirationDate") or ref.get("expiration")
    if not exp:
        return None
    try:
        return date.fromisoformat(str(exp)[:10])
    except ValueError:
        return None


def _ms_to_iso_utc(ms: int | float | None) -> str | None:
    if ms is None:
        return None
    try:
        ts = datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC)
        return ts.isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def normalize_equity_quote_entry(symbol: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one symbol entry from GET /marketdata/v1/quotes into stub-compatible keys."""
    q = entry.get("quote") if isinstance(entry.get("quote"), dict) else entry
    if not isinstance(q, dict):
        q = entry
    bid = q.get("bidPrice") if q.get("bidPrice") is not None else q.get("bid")
    ask = q.get("askPrice") if q.get("askPrice") is not None else q.get("ask")
    last = q.get("lastPrice") if q.get("lastPrice") is not None else q.get("last")
    mark = q.get("mark") if q.get("mark") is not None else q.get("markPrice")
    t_raw = (
        q.get("quoteTimeInLong")
        or q.get("tradeTimeInLong")
        or q.get("quoteTime")
        or q.get("lastUpdate")
    )
    quote_time: str | None
    if isinstance(t_raw, (int, float)):
        quote_time = _ms_to_iso_utc(t_raw)
    elif isinstance(t_raw, str):
        quote_time = t_raw
    else:
        quote_time = None
    vol = q.get("totalVolume")
    if vol is None:
        vol = q.get("lastSize")
    try:
        vol_i = int(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol_i = None
    out: dict[str, Any] = {
        "symbol": symbol.upper(),
        "bid": float(bid) if bid is not None else None,
        "ask": float(ask) if ask is not None else None,
        "last": float(last) if last is not None else None,
        "mark": float(mark) if mark is not None else None,
        "bidSize": int(q["bidSize"]) if q.get("bidSize") is not None else None,
        "askSize": int(q["askSize"]) if q.get("askSize") is not None else None,
        "totalVolume": vol_i,
        "quoteTime": quote_time,
        "_schwab": entry,
    }
    # OPTION (and some mixed) payloads nest Greeks and contract metadata under `quote` / `reference`.
    for greek in ("delta", "gamma", "theta", "vega", "rho"):
        if greek in q:
            out[greek] = _opt_float(q.get(greek))
    if "volatility" in q or "impliedVolatility" in q:
        iv = q.get("impliedVolatility")
        if iv is None:
            iv = q.get("volatility")
        out["implied_volatility"] = _opt_float(iv)
    if "openInterest" in q:
        out["open_interest"] = _opt_int(q.get("openInterest"))
    if "volume" in q and q.get("volume") is not None:
        out["volume"] = _opt_int(q.get("volume"))

    ref = entry.get("reference")
    if isinstance(ref, dict):
        u = ref.get("underlying")
        if u is not None:
            out["underlying_symbol"] = str(u).strip().upper()
        if "strikePrice" in ref or ref.get("strikePrice") is not None:
            out["strike"] = _opt_float(ref.get("strikePrice"))
        ct = ref.get("contractType") or ref.get("putCall")
        if isinstance(ct, str):
            cup = ct.strip().upper()
            if cup in ("CALL", "PUT"):
                out["option_type"] = cup
        exp_d = _parse_ref_expiration(ref)
        if exp_d is not None:
            out["expiration"] = exp_d

    return out


def normalize_quotes_response(body: dict[str, Any], requested: list[str]) -> dict[str, Any]:
    """Body is top-level JSON from get_quotes; keys are symbols."""
    out: dict[str, Any] = {}
    for sym in requested:
        key = sym
        entry = body.get(sym) or body.get(sym.upper())
        if not isinstance(entry, dict):
            for k, v in body.items():
                if isinstance(k, str) and k.upper() == sym.upper() and isinstance(v, dict):
                    entry = v
                    break
        if not isinstance(entry, dict):
            log.debug("no quote entry for symbol %s", sym)
            continue
        out[sym.upper()] = normalize_equity_quote_entry(sym, entry)
    return {"quotes": out}


def _underlying_price(payload: dict[str, Any]) -> float | None:
    up = payload.get("underlyingPrice")
    if up is not None:
        try:
            return float(up)
        except (TypeError, ValueError):
            pass
    und = payload.get("underlying")
    if isinstance(und, dict):
        for k in ("last", "mark", "closePrice", "lastPrice"):
            v = und.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
    return None


def flatten_option_chain(payload: dict[str, Any], *, underlying: str) -> dict[str, Any]:
    """Turn Schwab option chain JSON into the shape expected by DataResolver."""
    contracts: list[dict[str, Any]] = []
    u = underlying.upper()
    for side_map, put_call in (
        ("callExpDateMap", "CALL"),
        ("putExpDateMap", "PUT"),
    ):
        mp = payload.get(side_map)
        if not isinstance(mp, dict):
            continue
        for _exp_key, strike_map in mp.items():
            if not isinstance(strike_map, dict):
                continue
            for _strike_key, rows in strike_map.items():
                if not isinstance(rows, list):
                    continue
                for c in rows:
                    if not isinstance(c, dict):
                        continue
                    sym = c.get("symbol") or c.get("symbolDescription") or ""
                    exp = c.get("expirationDate") or c.get("expiration")
                    if exp and not isinstance(exp, str):
                        exp = str(exp)[:10]
                    strike = c.get("strikePrice")
                    if strike is None:
                        try:
                            strike = float(_strike_key)
                        except (TypeError, ValueError):
                            strike = None
                    ctype = c.get("putCall") or put_call
                    contracts.append(
                        {
                            "symbol": str(sym).strip(),
                            "underlying": c.get("underlyingSymbol") or u,
                            "expiration": exp,
                            "strike": float(strike) if strike is not None else None,
                            "contractType": str(ctype).upper()
                            if ctype
                            else put_call,
                            "bid": c.get("bid")
                            if c.get("bid") is not None
                            else c.get("bidPrice"),
                            "ask": c.get("ask")
                            if c.get("ask") is not None
                            else c.get("askPrice"),
                            "last": c.get("last")
                            if c.get("last") is not None
                            else c.get("lastPrice"),
                            "mark": c.get("mark")
                            if c.get("mark") is not None
                            else c.get("markPrice"),
                            "delta": c.get("delta"),
                        }
                    )
    now = datetime.now(UTC).isoformat()
    return {
        "underlying": u,
        "underlyingPrice": _underlying_price(payload),
        "contracts": contracts,
        "requestedAt": now,
        "includeQuotes": True,
    }


def schwab_candles_to_bars(
    symbol: str,
    timeframe: str,
    candles: list[dict[str, Any]],
) -> list[Bar]:
    """Convert Schwab priceHistory `candles` array into gateway Bar models."""
    bars: list[Bar] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        dt = c.get("datetime")
        if dt is None:
            dt = c.get("time")
        try:
            if isinstance(dt, (int, float)):
                x = float(dt)
                # Schwab equity candles use ms since epoch; some payloads use seconds.
                if x > 1e12:
                    ts = datetime.fromtimestamp(x / 1000.0, tz=UTC)
                elif x > 1e9:
                    ts = datetime.fromtimestamp(x, tz=UTC)
                else:
                    continue
            elif isinstance(dt, str):
                ts = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            else:
                continue
        except (OSError, OverflowError, ValueError):
            continue
        if timeframe == "1d":
            # Align with `stocks_1_day.date`: US trading session calendar date at UTC midnight.
            session_d = ts.astimezone(_NY).date()
            ts = datetime.combine(session_d, time.min, tzinfo=UTC)
        o = c.get("open")
        h = c.get("high")
        l = c.get("low")
        cl = c.get("close")
        if o is None or h is None or l is None or cl is None:
            continue
        vol = c.get("volume")
        try:
            vi = int(vol) if vol is not None else None
        except (TypeError, ValueError):
            vi = None
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=ts,
                timeframe=timeframe,
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(cl),
                volume=vi,
                source="live_schwab",
            )
        )
    if not bars and candles:
        log.warning(
            "schwab_candles_to_bars parsed 0 bars from %d candles (timeframe=%s); first keys=%s",
            len(candles),
            timeframe,
            list(candles[0].keys()) if candles and isinstance(candles[0], dict) else None,
        )
    bars.sort(key=lambda b: b.timestamp)
    return bars
