from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from market_gateway.app.core.models import OptionChainRequest
from market_gateway.app.core.time_utils import ensure_utc


def quote_key(symbol: str) -> str:
    return f"quote:{symbol.upper()}"


def option_quote_key(option_symbol: str) -> str:
    return f"option_quote:{option_symbol}"


def option_chain_key(req: OptionChainRequest) -> str:
    h = option_chain_params_hash(req)
    return f"option_chain:{req.symbol.upper()}:{h}"


def option_chain_params_hash(req: OptionChainRequest) -> str:
    payload: dict[str, Any] = {
        "symbol": req.symbol.upper(),
        "contract_type": req.contract_type,
        "expiration": req.expiration.isoformat() if req.expiration else None,
        "from_date": req.from_date.isoformat() if req.from_date else None,
        "to_date": req.to_date.isoformat() if req.to_date else None,
        "strike_count": req.strike_count,
        "include_quotes": req.include_quotes,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def history_live_key(symbol: str, timeframe: str, day: str) -> str:
    return f"history_live:{symbol.upper()}:{timeframe}:{day}"


def history_live_cov_key(symbol: str, timeframe: str, day: str) -> str:
    """Tracks the UTC [lo, hi] request window merged into history_live for that day."""
    return f"history_live_cov:{symbol.upper()}:{timeframe}:{day}"


def history_live_backfill_miss_key(
    symbol: str, timeframe: str, win_s: datetime, win_e: datetime
) -> str:
    """Negative cache: Schwab backfill was attempted for this window but coverage is still incomplete."""
    ws = ensure_utc(win_s).isoformat()
    we = ensure_utc(win_e).isoformat()
    payload = f"{symbol.upper()}|{timeframe}|{ws}|{we}"
    h = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return f"history_live_bf_miss:{symbol.upper()}:{timeframe}:{h}"


def positions_key() -> str:
    return "positions"


def orders_open_key() -> str:
    return "orders:open"


def order_preview_key(preview_id: str) -> str:
    return f"order_preview:{preview_id}"
