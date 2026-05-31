from market_gateway.schwab.option_symbol import (
    gateway_option_symbol,
    is_option_contract_symbol,
    schwab_option_symbol,
)


def test_underscore_to_osi_spy_call() -> None:
    assert schwab_option_symbol("SPY_20260601C00756000") == "SPY   260601C00756000"


def test_underscore_to_osi_spy_put() -> None:
    assert schwab_option_symbol("SPY_20260601P00755000") == "SPY   260601P00755000"


def test_passthrough_osi_form() -> None:
    s = "SPY   260601C00756000"
    assert schwab_option_symbol(s) == s


def test_passthrough_strips_whitespace() -> None:
    assert schwab_option_symbol("  SPY   260601C00756000  ") == "SPY   260601C00756000"


def test_is_option_contract_symbol_osi_and_gateway() -> None:
    assert is_option_contract_symbol("SPY_20260601C00756000")
    assert is_option_contract_symbol("SPY   260601C00756000")
    assert not is_option_contract_symbol("SPY")
    assert not is_option_contract_symbol("SPY_20260601C0075600")


def test_gateway_option_symbol_roundtrip() -> None:
    g = "SPY_20260601C00756000"
    osi = schwab_option_symbol(g)
    assert gateway_option_symbol(osi) == g
    assert gateway_option_symbol(g) == g
