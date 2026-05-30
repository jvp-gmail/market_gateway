def test_status_requires_auth(client) -> None:
    r = client.get("/status")
    assert r.status_code == 401


def test_status_ok(client, auth_headers) -> None:
    r = client.get("/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["redis"] == "ok"
    assert body["database"] in ("not_configured", "ok", "error")
