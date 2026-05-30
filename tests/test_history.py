def test_history_requires_auth(client) -> None:
    r = client.get("/history/SPY?timeframe=1m&lookback_days=1")
    assert r.status_code == 401


def test_history_sample_bars(client, auth_headers) -> None:
    r = client.get(
        "/history/SPY?timeframe=1m&lookback_days=2&mode=historical_only",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "SPY"
    assert body["mode"] == "historical_only"
    assert len(body["bars"]) >= 1
    assert body["bars"][0]["source"] == "sample"
