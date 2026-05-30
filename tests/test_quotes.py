def test_quotes_requires_auth(client) -> None:
    r = client.get("/quotes?symbols=SPY")
    assert r.status_code == 401


def test_quotes_deterministic_sample(client, auth_headers) -> None:
    r = client.get("/quotes?symbols=AAPL,NVDA", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert {q["symbol"] for q in data} == {"AAPL", "NVDA"}
    r2 = client.get("/quotes?symbols=AAPL,NVDA", headers=auth_headers)
    assert r2.json()[0]["bid"] == data[0]["bid"]
