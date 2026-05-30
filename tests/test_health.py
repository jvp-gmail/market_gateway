def test_health_ok(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["service"] == "market_gateway"
