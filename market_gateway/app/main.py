from __future__ import annotations

import asyncio
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
from market_gateway.schwab.factory import create_schwab_market_client

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = logging.getLogger(__name__)


def create_app(*, redis_client: Redis | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()
        if redis_client is None:
            # URL query options win over kwargs in redis-py's from_url(); patch pool so
            # socket_timeout can be None (required for XREAD BLOCK used by SSE).
            rc = redis.from_url(settings.redis_url, decode_responses=True)
            pool = rc.connection_pool
            pool.connection_kwargs["socket_timeout"] = (
                settings.redis_socket_timeout_seconds
            )
            pool.connection_kwargs["socket_connect_timeout"] = (
                settings.redis_socket_connect_timeout_seconds
            )
        else:
            rc = redis_client
        try:
            await rc.ping()
        except Exception as e:
            log.warning("redis ping failed at startup: %s", e)

        historical = await create_historical_store(settings.resolved_asyncpg_dsn())
        live = LiveCache(rc)
        schwab = await create_schwab_market_client(settings)
        resolver = DataResolver(settings, historical, live, schwab)
        bus = EventBus(
            rc,
            settings.event_stream_name,
            xread_block_ms=settings.event_bus_xread_block_ms,
        )
        await bus.ensure_stream_exists()

        app.state.settings = settings
        app.state.redis = rc
        app.state.historical_store = historical
        app.state.schwab_client = schwab
        app.state.resolver = resolver
        app.state.event_bus = bus

        stub_task: asyncio.Task | None = None
        if settings.enable_quote_stream_stub:
            from market_gateway.app.services.quote_stream_stub import run_quote_stream_stub

            stub_task = asyncio.create_task(run_quote_stream_stub(bus, settings))

        yield

        if stub_task is not None:
            stub_task.cancel()
            try:
                await stub_task
            except asyncio.CancelledError:
                pass

        closer_schwab = getattr(schwab, "aclose", None)
        if closer_schwab is not None:
            await closer_schwab()

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
