"""Tests for Schwab LEVELONE_EQUITIES row → QuoteSnapshot mapping."""

from __future__ import annotations

from datetime import UTC, datetime

from market_gateway.schwab.stream_equity_normalize import (
    level_one_equity_row_to_quote_snapshot,
    level_one_option_row_to_option_contract_quote,
)
from market_gateway.schwab.stream_equity_runner import partition_equity_and_futures_symbols


def test_level_one_equity_row_to_quote_snapshot_minimal() -> None:
    row = {
        "SYMBOL": "SPY",
        "BID_PRICE": "100",
        "ASK_PRICE": "100.05",
        "LAST_PRICE": "100.02",
        "MARK": "100.03",
        "BID_SIZE": 10,
        "ASK_SIZE": 20,
        "TOTAL_VOLUME": 1_234_567,
        "QUOTE_TIME_MILLIS": 1_700_000_000_000,
    }
    q = level_one_equity_row_to_quote_snapshot(row)
    assert q is not None
    assert q.symbol == "SPY"
    assert q.bid == 100.0
    assert q.ask == 100.05
    assert q.last == 100.02
    assert q.mark == 100.03
    assert q.bid_size == 10
    assert q.ask_size == 20
    assert q.volume == 1_234_567
    assert q.source == "live_schwab_stream"
    assert q.event_ts == datetime.fromtimestamp(1_700_000_000_000 / 1000.0, tz=UTC)


def test_level_one_option_row_to_option_contract_quote() -> None:
    row = {
        "key": "SPY   260601C00756000",
        "BID_PRICE": 1.5,
        "ASK_PRICE": 1.55,
        "DELTA": 0.42,
        "VOLATILITY": 0.22,
        "QUOTE_TIME_MILLIS": 1_700_000_000_000,
    }
    oc = level_one_option_row_to_option_contract_quote(row)
    assert oc is not None
    assert oc.option_symbol == "SPY   260601C00756000"
    assert oc.underlying_symbol == "SPY"
    assert oc.strike == 756.0
    assert oc.option_type == "CALL"
    assert oc.bid == 1.5
    assert oc.delta == 0.42
    assert oc.implied_volatility == 0.22
    assert oc.source == "live_schwab_stream"


def test_partition_equity_and_futures_symbols() -> None:
    eq, fu = partition_equity_and_futures_symbols(["spy", "/es", " QQQ ", "/MES"])
    assert eq == ["QQQ", "SPY"]
    assert fu == ["/ES", "/MES"]


def test_level_one_equity_row_missing_symbol_returns_none() -> None:
    assert level_one_equity_row_to_quote_snapshot({}) is None
    assert level_one_equity_row_to_quote_snapshot({"BID_PRICE": 1.0}) is None


def test_level_one_equity_row_symbol_from_field_zero() -> None:
    """If ``SYMBOL`` is absent, use Schwab field index ``0`` (raw or partial relabel)."""
    row = {"0": "QQQ", "BID_PRICE": 400.0, "ASK_PRICE": 400.05}
    q = level_one_equity_row_to_quote_snapshot(row)
    assert q is not None
    assert q.symbol == "QQQ"
    assert q.bid == 400.0
    assert q.ask == 400.05


def test_level_one_equity_row_symbol_from_schwab_key() -> None:
    """Schwab L1 ``content`` uses ``key`` for symbol (not field ``0``)."""
    row = {
        "key": "QQQ",
        "BID_PRICE": 737.65,
        "ASK_PRICE": 737.98,
        "LAST_PRICE": 737.98,
        "BID_SIZE": 40,
        "ASK_SIZE": 120,
        "TOTAL_VOLUME": 37_541_668,
        "MARK": 738.31,
        "QUOTE_TIME_MILLIS": 1_780_099_199_383,
    }
    q = level_one_equity_row_to_quote_snapshot(row)
    assert q is not None
    assert q.symbol == "QQQ"
    assert q.bid == 737.65
    assert q.ask == 737.98
    assert q.last == 737.98


def test_level_one_futures_row_symbol_from_schwab_key() -> None:
    row = {
        "key": "/ES",
        "BID_PRICE": 7614.5,
        "ASK_PRICE": 7614.75,
        "LAST_PRICE": 7614.75,
        "BID_SIZE": 19,
        "ASK_SIZE": 4,
        "TOTAL_VOLUME": 48412,
        "QUOTE_TIME_MILLIS": 1_780_282_302_443,
        "MARK": 7614.75,
    }
    q = level_one_equity_row_to_quote_snapshot(row)
    assert q is not None
    assert q.symbol == "/ES"
