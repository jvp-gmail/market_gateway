"""Map Schwab streaming LEVELONE_* rows to ``QuoteSnapshot`` / ``OptionContractQuote``."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from market_gateway.app.core.models import OptionContractQuote, QuoteSnapshot
from market_gateway.app.core.time_utils import utc_now
from market_gateway.schwab.option_symbol import gateway_option_symbol, parse_osi_option_contract


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


def _option_contract_type(v: Any) -> Literal["CALL", "PUT"] | None:
    if v is None or v == "":
        return None
    s = str(v).strip().upper()
    if s in ("C", "CALL", "CALLS"):
        return "CALL"
    if s in ("P", "PUT", "PUTS"):
        return "PUT"
    return None


def _option_expiration_from_row(row: dict[str, Any]) -> date | None:
    ey = _opt_int(row.get("EXPIRATION_YEAR"))
    em = _opt_int(row.get("EXPIRATION_MONTH"))
    ed = _opt_int(row.get("EXPIRATION_DAY"))
    if ey is None or em is None or ed is None:
        return None
    try:
        return date(ey, em, ed)
    except ValueError:
        return None


def level_one_option_row_to_option_contract_quote(row: dict[str, Any]) -> OptionContractQuote | None:
    """
    One ``content`` element from ``LEVELONE_OPTIONS``.

    Uses the same ``key`` / ``SYMBOL`` resolution as equities; maps Schwab L1 option
    fields (after schwab-py relabeling) into ``OptionContractQuote``. OSI in the row
    fills strike / expiration / side when stream fields omit them.
    """
    raw_sym = _row_symbol(row)
    if not raw_sym:
        return None
    compact = gateway_option_symbol(raw_sym)
    parsed = parse_osi_option_contract(compact)
    underlying_raw = row.get("UNDERLYING")
    underlying: str | None = None
    if underlying_raw is not None and str(underlying_raw).strip():
        underlying = str(underlying_raw).strip().upper()
    exp = _option_expiration_from_row(row)
    ctype = _option_contract_type(row.get("CONTRACT_TYPE"))
    strike: float | None = None
    if parsed:
        if underlying is None:
            underlying = parsed[0]
        if exp is None:
            exp = parsed[1]
        if ctype is None:
            ctype = parsed[2]
        strike = parsed[3]

    now = utc_now()
    event_ts = _quote_time_ms_to_dt(row.get("QUOTE_TIME_MILLIS"))
    return OptionContractQuote(
        option_symbol=compact,
        underlying_symbol=underlying,
        expiration=exp,
        strike=strike,
        option_type=ctype,
        event_ts=event_ts,
        received_ts=now,
        bid=_opt_float(row.get("BID_PRICE")),
        ask=_opt_float(row.get("ASK_PRICE")),
        bid_size=_opt_int(row.get("BID_SIZE")),
        ask_size=_opt_int(row.get("ASK_SIZE")),
        last=_opt_float(row.get("LAST_PRICE")),
        mark=_opt_float(row.get("MARK")),
        delta=_opt_float(row.get("DELTA")),
        gamma=_opt_float(row.get("GAMMA")),
        theta=_opt_float(row.get("THETA")),
        vega=_opt_float(row.get("VEGA")),
        rho=_opt_float(row.get("RHO")),
        implied_volatility=_opt_float(row.get("VOLATILITY")),
        open_interest=_opt_int(row.get("OPEN_INTEREST")),
        volume=_opt_int(row.get("TOTAL_VOLUME")),
        source="live_schwab_stream",
        raw=row,
    )


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
