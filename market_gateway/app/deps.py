from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request

from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.stream_symbols import StreamSymbolsPayload
from market_gateway.app.services.data_resolver import DataResolver


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_resolver(request: Request) -> DataResolver:
    return request.app.state.resolver


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_redis(request: Request):
    return request.app.state.redis


def get_stream_symbol_replace_queue(request: Request) -> asyncio.Queue[StreamSymbolsPayload]:
    """Queue consumed by the Schwab stream task for session-level SUBS changes."""
    q = getattr(request.app.state, "stream_symbol_replace_queue", None)
    if q is None:
        raise HTTPException(
            status_code=503,
            detail="Schwab quote stream is not active (enable streaming and non-empty SCHWAB_STREAM_* symbol lists).",
        )
    return q
