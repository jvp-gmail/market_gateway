"""Unit tests for Schwab JSON normalization (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from market_gateway.schwab.normalize import (
    flatten_option_chain,
    normalize_equity_quote_entry,
    normalize_quotes_response,
    schwab_candles_to_bars,
)


def test_normalize_equity_quote_from_nested_quote() -> None:
    raw = {
        "assetMainType": "EQUITY",
        "quote": {
            "bidPrice": 100.0,
            "askPrice": 100.05,
            "lastPrice": 100.02,
            "mark": 100.03,
            "bidSize": 10,
            "askSize": 20,
            "totalVolume": 1_234_567,
            "quoteTimeInLong": 1_700_000_000_000,
        },
    }
    q = normalize_equity_quote_entry("aapl", raw)
    assert q["symbol"] == "AAPL"
    assert q["bid"] == 100.0
    assert q["ask"] == 100.05
    assert q["last"] == 100.02
    assert q["mark"] == 100.03
    assert q["bidSize"] == 10
    assert q["askSize"] == 20
    assert q["totalVolume"] == 1_234_567
    assert q["quoteTime"] is not None
    assert "delta" not in q


def test_normalize_option_quote_entry_pulls_greeks_and_reference() -> None:
    """GET /quotes OPTION rows carry Greeks on `quote` and contract fields on `reference`."""
    raw = {
        "assetMainType": "OPTION",
        "quote": {
            "bidPrice": 1.1,
            "askPrice": 1.2,
            "lastPrice": 1.15,
            "mark": 1.12,
            "bidSize": 10,
            "askSize": 20,
            "totalVolume": 500,
            "delta": 0.52,
            "gamma": 0.03,
            "theta": -0.04,
            "vega": 0.11,
            "rho": 0.01,
            "volatility": 0.28,
            "openInterest": 12_345,
            "quoteTimeInLong": 1_700_000_000_000,
        },
        "reference": {
            "underlying": "SPY",
            "strikePrice": 400.0,
            "contractType": "CALL",
            "expirationDate": "2026-06-19",
        },
    }
    q = normalize_equity_quote_entry("SPY_20260619C00400000", raw)
    assert q["delta"] == 0.52
    assert q["gamma"] == 0.03
    assert q["theta"] == -0.04
    assert q["vega"] == 0.11
    assert q["rho"] == 0.01
    assert q["implied_volatility"] == 0.28
    assert q["open_interest"] == 12_345
    assert q["underlying_symbol"] == "SPY"
    assert q["strike"] == 400.0
    assert q["option_type"] == "CALL"
    assert q["expiration"] == date(2026, 6, 19)


def test_normalize_quotes_response_option_symbol() -> None:
    body = {
        "SPY_20260619C00400000": {
            "assetMainType": "OPTION",
            "quote": {"bidPrice": 1.0, "askPrice": 1.1, "delta": 0.4},
            "reference": {"underlying": "SPY", "contractType": "CALL"},
        }
    }
    r = normalize_quotes_response(body, ["SPY_20260619C00400000"])
    q = r["quotes"]["SPY_20260619C00400000"]
    assert q["delta"] == 0.4
    assert q["underlying_symbol"] == "SPY"


def test_flatten_option_chain_minimal() -> None:
    payload = {
        "underlyingPrice": 210.5,
        "callExpDateMap": {
            "2026-06-19:1": {
                "200.0": [
                    {
                        "symbol": "SPY_20260619C00200000",
                        "putCall": "CALL",
                        "strikePrice": 200.0,
                        "expirationDate": "2026-06-19",
                        "bid": 1.1,
                        "ask": 1.2,
                        "mark": 1.15,
                        "delta": 0.5,
                    }
                ]
            }
        },
        "putExpDateMap": {},
    }
    flat = flatten_option_chain(payload, underlying="SPY")
    assert flat["underlying"] == "SPY"
    assert flat["underlyingPrice"] == 210.5
    assert len(flat["contracts"]) == 1
    c = flat["contracts"][0]
    assert c["symbol"] == "SPY_20260619C00200000"
    assert c["contractType"] == "CALL"
    assert c["strike"] == 200.0


def test_schwab_candles_to_bars_ms_datetime() -> None:
    ms = int(datetime(2026, 1, 15, 16, 0, tzinfo=UTC).timestamp() * 1000)
    candles = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "datetime": ms}]
    bars = schwab_candles_to_bars("SPY", "1m", candles)
    assert len(bars) == 1
    assert bars[0].symbol == "SPY"
    assert bars[0].timeframe == "1m"
    assert bars[0].source == "live_schwab"
    assert bars[0].close == 1.5


def test_schwab_daily_bar_snaps_to_ny_session_utc_midnight() -> None:
    """Daily bars use US session date at UTC midnight (matches stocks_1_day convention)."""
    # 2026-01-15 22:00 UTC = 2026-01-15 17:00 America/New_York (EST) — same calendar date in NY.
    ms = int(datetime(2026, 1, 15, 22, 0, tzinfo=UTC).timestamp() * 1000)
    candles = [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "datetime": ms}]
    bars = schwab_candles_to_bars("SPY", "1d", candles)
    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC)
