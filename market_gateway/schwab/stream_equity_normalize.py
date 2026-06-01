"""Map Schwab streaming LEVELONE_EQUITIES / LEVELONE_FUTURES rows to ``QuoteSnapshot``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from market_gateway.app.core.models import QuoteSnapshot
from market_gateway.app.core.time_utils import utc_now


def _quote_time_ms_to_dt(ms: Any) -> datetime | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC)
    except (OSError, OverflowError, ValueError, TypeError):
        return None


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _row_symbol(row: dict[str, Any]) -> str | None:
    """Resolve ticker from schwab-py relabeled rows or Schwab's native L1 shape."""
    sym = row.get("SYMBOL")
    if sym is not None and str(sym).strip():
        return str(sym).strip().upper()
    # Legacy / alternate: Schwab field index ``0`` (when present).
    alt = row.get("0")
    if alt is not None and str(alt).strip():
        return str(alt).strip().upper()
    # Current Schwab streaming sends the symbol as ``key``, not field ``0`` (see LEVELONE_* ``content``).
    k = row.get("key")
    if k is not None and str(k).strip():
        return str(k).strip().upper()
    return None


def level_one_equity_row_to_quote_snapshot(row: dict[str, Any]) -> QuoteSnapshot | None:
    """
    One ``content`` element from LEVELONE_EQUITIES or LEVELONE_FUTURES.

    Schwab sends the ticker in ``key``; numeric fields may be relabeled by schwab-py
    to names like ``BID_PRICE``, ``QUOTE_TIME_MILLIS``, etc.
    """
    symbol = _row_symbol(row)
    if not symbol:
        return None
    now = utc_now()
    event_ts = _quote_time_ms_to_dt(row.get("QUOTE_TIME_MILLIS"))
    return QuoteSnapshot(
        symbol=symbol,
        event_ts=event_ts,
        received_ts=now,
        bid=_opt_float(row.get("BID_PRICE")),
        ask=_opt_float(row.get("ASK_PRICE")),
        bid_size=_opt_int(row.get("BID_SIZE")),
        ask_size=_opt_int(row.get("ASK_SIZE")),
        last=_opt_float(row.get("LAST_PRICE")),
        mark=_opt_float(row.get("MARK")),
        volume=_opt_int(row.get("TOTAL_VOLUME")),
        source="live_schwab_stream",
        raw=row,
    )
