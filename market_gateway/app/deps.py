from __future__ import annotations

from fastapi import Request

from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.services.data_resolver import DataResolver


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_resolver(request: Request) -> DataResolver:
    return request.app.state.resolver


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_redis(request: Request):
    return request.app.state.redis
