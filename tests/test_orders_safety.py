def test_order_submit_requires_preview(client, auth_headers) -> None:
    r = client.post(
        "/orders/submit",
        headers=auth_headers,
        json={
            "preview_id": "00000000-0000-0000-0000-000000000000",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 1,
        },
    )
    assert r.status_code == 400


def test_order_submit_paper_stub(client, auth_headers) -> None:
    prev = client.post(
        "/orders/preview",
        headers=auth_headers,
        json={"symbol": "SPY", "side": "BUY", "quantity": 2},
    )
    assert prev.status_code == 200
    pid = prev.json()["preview_id"]
    sub = client.post(
        "/orders/submit",
        headers=auth_headers,
        json={"preview_id": pid, "symbol": "SPY", "side": "BUY", "quantity": 2},
    )
    assert sub.status_code == 200
    body = sub.json()
    assert body["mode"] == "paper"
    assert "stub" in body["message"].lower() or body["order_id"]


def test_order_preview_publishes_event(client, auth_headers) -> None:
    client.post(
        "/orders/preview",
        headers=auth_headers,
        json={"symbol": "QQQ", "side": "SELL", "quantity": 1},
    )
    recent = client.get("/events/recent?count=5", headers=auth_headers)
    assert recent.status_code == 200
    types = {e["event_type"] for e in recent.json()}
    assert "order_preview" in types
