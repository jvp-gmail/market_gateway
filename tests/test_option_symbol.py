from market_gateway.schwab.option_symbol import schwab_option_symbol


def test_underscore_to_osi_spy_call() -> None:
    assert schwab_option_symbol("SPY_20260601C00756000") == "SPY   260601C00756000"


def test_underscore_to_osi_spy_put() -> None:
    assert schwab_option_symbol("SPY_20260601P00755000") == "SPY   260601P00755000"


def test_passthrough_osi_form() -> None:
    s = "SPY   260601C00756000"
    assert schwab_option_symbol(s) == s


def test_passthrough_strips_whitespace() -> None:
    assert schwab_option_symbol("  SPY   260601C00756000  ") == "SPY   260601C00756000"
