from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from market_gateway.app.core.time_utils import utc_now


class StubSchwabClient:
    """Phase 1: deterministic sample payloads; no network or credentials."""

    @property
    def quote_source_label(self) -> str:
        return "sample"

    async def aclose(self) -> None:
        return None

    async def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        now = utc_now()
        out: dict[str, Any] = {}
        for i, sym in enumerate(symbols):
            s = sym.upper()
            base = 180.0 + (hash(s) % 200) + i * 0.5
            out[s] = {
                "symbol": s,
                "bid": round(base - 0.02, 2),
                "ask": round(base + 0.02, 2),
                "last": round(base, 2),
                "mark": round(base, 2),
                "bidSize": 100,
                "askSize": 200,
                "totalVolume": 1_000_000 + i * 10_000,
                "quoteTime": now.isoformat(),
            }
        return {"quotes": out}

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
        now = utc_now()
        u = symbol.upper()
        exp = expiration or (now.date() + timedelta(days=30))
        strikes = [200.0, 205.0, 210.0]
        if strike_count:
            strikes = strikes[: max(1, min(strike_count, len(strikes)))]
        contracts: list[dict[str, Any]] = []
        for strike in strikes:
            for typ, suffix in (("CALL", "C"), ("PUT", "P")):
                if contract_type in ("CALL", "PUT") and contract_type != typ:
                    continue
                osym = f"{u}_{exp.strftime('%Y%m%d')}{suffix}{int(strike * 1000):08d}"
                contracts.append(
                    {
                        "symbol": osym,
                        "underlying": u,
                        "expiration": exp.isoformat(),
                        "strike": strike,
                        "contractType": typ,
                        "bid": round(strike * 0.01, 2),
                        "ask": round(strike * 0.0105, 2),
                        "mark": round(strike * 0.0102, 2),
                        "delta": 0.45 if typ == "CALL" else -0.45,
                    }
                )
        return {
            "underlying": u,
            "underlyingPrice": 208.5,
            "contracts": contracts,
            "requestedAt": now.isoformat(),
            "includeQuotes": include_quotes,
        }

    async def get_option_quotes(self, option_symbols: list[str]) -> dict[str, Any]:
        now = utc_now()
        q: dict[str, Any] = {}
        for osym in option_symbols:
            q[osym] = {
                "symbol": osym,
                "bid": 1.25,
                "ask": 1.35,
                "mark": 1.30,
                "delta": 0.52,
                "quoteTime": now.isoformat(),
            }
        return {"quotes": q}

    async def get_price_history(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        lookback_days: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        end = end or now
        if start is None and lookback_days:
            start = end - timedelta(days=lookback_days)
        start = start or (end - timedelta(days=1))
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "candles": [],
        }

    async def get_positions(self) -> dict[str, Any]:
        return {
            "positions": [
                {"symbol": "SPY", "quantity": 100, "averagePrice": 500.0},
            ]
        }

    async def preview_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "estimatedNotional": order.get("quantity", 1) * 150.0}

    async def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "orderId": "stub-order", "raw": order}
