"""Tests for Schwab stream symbol payload and events API."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from market_gateway.app.core.stream_symbols import StreamSymbolsPayload


def test_stream_symbols_payload_normalizes() -> None:
    p = StreamSymbolsPayload(equities=[" spy ", "QQQ"], futures=["/es"], options=[])
    assert p.equities == ["QQQ", "SPY"]
    assert p.futures == ["/ES"]


def test_stream_symbols_futures_must_have_slash() -> None:
    with pytest.raises(ValidationError):
        StreamSymbolsPayload(equities=[], futures=["ES"], options=[])


def test_put_stream_symbols_503_when_stream_inactive(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put(
        "/events/stream/symbols",
        json={"equities": ["SPY"], "futures": [], "options": []},
        headers=auth_headers,
    )
    assert r.status_code == 503


def test_put_stream_symbols_200_when_options_nonempty(client: TestClient, auth_headers: dict[str, str]) -> None:
    client.app.state.stream_symbol_replace_queue = asyncio.Queue()
    r = client.put(
        "/events/stream/symbols",
        json={"equities": ["SPY"], "futures": [], "options": ["SPY   250321C00500000"]},
        headers=auth_headers,
    )
    assert r.status_code == 200


def test_put_stream_symbols_400_when_all_lists_empty(client: TestClient, auth_headers: dict[str, str]) -> None:
    client.app.state.stream_symbol_replace_queue = asyncio.Queue()
    r = client.put(
        "/events/stream/symbols",
        json={"equities": [], "futures": [], "options": []},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_put_stream_symbols_enqueues(client: TestClient, auth_headers: dict[str, str]) -> None:
    q: asyncio.Queue[StreamSymbolsPayload] = asyncio.Queue()
    client.app.state.stream_symbol_replace_queue = q
    r = client.put(
        "/events/stream/symbols",
        json={"equities": ["AAPL"], "futures": ["/MES"], "options": []},
        headers=auth_headers,
    )
    assert r.status_code == 200
    got = q.get_nowait()
    assert got.equities == ["AAPL"]
    assert got.futures == ["/MES"]


def test_put_stream_symbols_options_only_enqueues(client: TestClient, auth_headers: dict[str, str]) -> None:
    q: asyncio.Queue[StreamSymbolsPayload] = asyncio.Queue()
    client.app.state.stream_symbol_replace_queue = q
    r = client.put(
        "/events/stream/symbols",
        json={"equities": [], "futures": [], "options": ["SPY   250321C00500000"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    got = q.get_nowait()
    assert got.equities == []
    assert got.futures == []
    assert got.options == ["SPY   250321C00500000"]
