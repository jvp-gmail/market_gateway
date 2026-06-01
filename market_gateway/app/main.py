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


def _configure_market_gateway_logging() -> None:
    """Make ``market_gateway`` INFO logs visible under uvicorn (root often stays at WARNING)."""
    lg = logging.getLogger("market_gateway")
    if lg.handlers:
        lg.setLevel(logging.INFO)
        return
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    lg.propagate = False


def _configure_schwab_streaming_debug() -> None:
    """Verbose WebSocket traffic from schwab-py (``Send`` / ``Receive`` JSON). See ``SCHWAB_STREAMING_DEBUG``."""
    lg = logging.getLogger("schwab.streaming")
    lg.setLevel(logging.DEBUG)
    if not lg.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        lg.addHandler(handler)
    lg.propagate = False


def create_app(*, redis_client: Redis | None = None) -> FastAPI:
    _configure_market_gateway_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings()
        if settings.schwab_streaming_debug:
            _configure_schwab_streaming_debug()
            log.info("SCHWAB_STREAMING_DEBUG enabled — logging WebSocket frames at DEBUG")
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

        stream_task: asyncio.Task | None = None
        http = getattr(schwab, "http_client", None)
        if settings.enable_schwab_streaming and http is None:
            log.warning(
                "ENABLE_SCHWAB_STREAMING is true but Schwab client has no http_client — "
                "quote WebSocket not started. Use ENABLE_SCHWAB_LIVE_DATA plus SCHWAB_CLIENT_ID, "
                "SCHWAB_CLIENT_SECRET, SCHWAB_TOKEN_FILE so the live client loads (see startup logs)."
            )
        if settings.enable_schwab_streaming and http is not None:
            raw = (settings.schwab_stream_equity_symbols or "").strip()
            sym_list = [s.strip() for s in raw.split(",") if s.strip()]
            opt_raw = (settings.schwab_stream_options_symbols or "").strip()
            opt_list = [s.strip() for s in opt_raw.split(",") if s.strip()]
            if sym_list or opt_list:
                from market_gateway.app.core.stream_symbols import StreamSymbolsPayload
                from market_gateway.schwab.stream_equity_runner import (
                    partition_equity_and_futures_symbols,
                    run_schwab_equity_stream,
                )

                eq_syms, fut_syms = partition_equity_and_futures_symbols(sym_list)
                initial = StreamSymbolsPayload(
                    equities=eq_syms, futures=fut_syms, options=opt_list
                )
                replace_queue: asyncio.Queue[StreamSymbolsPayload] = asyncio.Queue(maxsize=8)
                app.state.stream_symbol_replace_queue = replace_queue
                log.info(
                    "Starting Schwab quote WebSocket (equities=%s futures=%s options=%s)",
                    eq_syms or "(none)",
                    fut_syms or "(none)",
                    initial.options or "(none)",
                )
                stream_task = asyncio.create_task(
                    run_schwab_equity_stream(http, bus, settings, replace_queue, initial)
                )
            else:
                log.warning(
                    "ENABLE_SCHWAB_STREAMING is true but both SCHWAB_STREAM_EQUITY_SYMBOLS and "
                    "SCHWAB_STREAM_OPTIONS_SYMBOLS are empty after parsing; not starting Schwab quote WebSocket"
                )

        yield

        if stream_task is not None:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass

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
