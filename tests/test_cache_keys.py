from market_gateway.app.core.cache_keys import option_chain_key, option_chain_params_hash
from market_gateway.app.core.models import OptionChainRequest


def test_option_chain_params_hash_stable() -> None:
    a = OptionChainRequest(symbol="SPY", strike_count=10)
    b = OptionChainRequest(symbol="SPY", strike_count=10)
    assert option_chain_params_hash(a) == option_chain_params_hash(b)


def test_option_chain_key_uses_hash() -> None:
    req = OptionChainRequest(symbol="aapl", expiration=None)
    k = option_chain_key(req)
    assert k.startswith("option_chain:AAPL:")
    assert len(k.split(":")[-1]) == 16
