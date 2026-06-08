from datetime import date

from market_gateway.schwab.option_symbol import (
    gateway_option_symbol,
    is_option_contract_symbol,
    normalize_option_to_compact,
    parse_osi_option_contract,
    schwab_option_symbol,
)


def test_schwab_from_legacy_underscore() -> None:
    assert schwab_option_symbol("SPY_20260601C00756000") == "SPY   260601C00756000"


def test_schwab_from_compact() -> None:
    assert schwab_option_symbol("SPY260601C00756000") == "SPY   260601C00756000"


def test_schwab_passthrough_padded() -> None:
    s = "SPY   260601C00756000"
    assert schwab_option_symbol(s) == s


def test_schwab_passthrough_strips_whitespace() -> None:
    assert schwab_option_symbol("  SPY   260601C00756000  ") == "SPY   260601C00756000"


def test_is_option_contract_symbol() -> None:
    assert is_option_contract_symbol("SPY_20260601C00756000")
    assert is_option_contract_symbol("SPY   260601C00756000")
    assert is_option_contract_symbol("SPY260601C00756000")
    assert is_option_contract_symbol("O:SPY260601C00756000")
    assert is_option_contract_symbol("BRK.B251201C00190000")
    assert is_option_contract_symbol("O:BRK.B251201C00190000")
    assert not is_option_contract_symbol("SPY")
    assert not is_option_contract_symbol("SPY_20260601C0075600")


def test_parse_osi_from_compact() -> None:
    out = parse_osi_option_contract("SPY260601C00756000")
    assert out is not None
    u, exp, cp, strike = out
    assert u == "SPY"
    assert exp.isoformat() == "2026-06-01"
    assert cp == "CALL"
    assert strike == 756.0


def test_parse_osi_invalid() -> None:
    assert parse_osi_option_contract("SPY") is None


def test_gateway_option_symbol_compact_and_legacy() -> None:
    assert gateway_option_symbol("SPY_20260601C00756000") == "SPY260601C00756000"
    assert gateway_option_symbol("SPY   260601C00756000") == "SPY260601C00756000"
    assert gateway_option_symbol("O:AAPL251201C00190000") == "AAPL251201C00190000"
    assert gateway_option_symbol("BRK.B251201C00190000") == "BRK.B251201C00190000"


def test_normalize_option_to_compact_roundtrip() -> None:
    g = "SPY_20260601C00756000"
    c = normalize_option_to_compact(g)
    assert c == "SPY260601C00756000"
    assert schwab_option_symbol(c) == "SPY   260601C00756000"
    assert gateway_option_symbol(schwab_option_symbol(c)) == c


def test_parse_century_closest_to_today() -> None:
    """YY resolved via century closest to today (see _yymmdd_to_date)."""
    out = parse_osi_option_contract("SPY080915C00100000")
    assert out is not None
    assert out[1] == date(2008, 9, 15)
