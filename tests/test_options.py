def test_options_chains_requires_auth(client) -> None:
    r = client.get("/options/chains?symbol=AAPL")
    assert r.status_code == 401


def test_options_chains_sample(client, auth_headers) -> None:
    r = client.get("/options/chains?symbol=AAPL", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL"
    assert len(body["contracts"]) >= 1


def test_options_quotes_sample(client, auth_headers) -> None:
    r = client.get(
        "/options/quotes?symbols=AAPL_20260619C00200000",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
