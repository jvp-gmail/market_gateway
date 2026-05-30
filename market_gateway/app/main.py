from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import redis.asyncio as redis
from fastapi import FastAPI

from market_gateway.app.api import events, health, history, options, orders, positions, quotes, status, strategies
from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.services.data_resolver import DataResolver
from market_gateway.app.services.historical_store import create_historical_store
from market_gateway.app.services.live_cache import LiveCache
from market_gateway.schwab.client import StubSchwabClient

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = logging.getLogger(__name__)


def create_app(*, redis_client: Redis | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()
        rc = redis_client or redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await rc.ping()
        except Exception as e:
            log.warning("redis ping failed at startup: %s", e)

        historical = await create_historical_store(settings.resolved_asyncpg_dsn())
        live = LiveCache(rc)
        schwab = StubSchwabClient()
        resolver = DataResolver(settings, historical, live, schwab)
        bus = EventBus(
            rc,
            settings.event_stream_name,
            xread_block_ms=settings.event_bus_xread_block_ms,
        )

        app.state.settings = settings
        app.state.redis = rc
        app.state.historical_store = historical
        app.state.schwab_client = schwab
        app.state.resolver = resolver
        app.state.event_bus = bus

        yield

        await rc.aclose()
        closer = getattr(historical, "close", None)
        if closer is not None:
            await closer()

    app = FastAPI(title="market_gateway", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(quotes.router)
    app.include_router(options.router)
    app.include_router(history.router)
    app.include_router(positions.router)
    app.include_router(orders.router)
    app.include_router(strategies.router)
    app.include_router(events.router)
    return app


# Run: uvicorn market_gateway.app.main:create_app --factory
