from fastapi import APIRouter, Depends, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.deps import get_settings_from_app
from market_gateway.app.services.historical_store import PostgresHistoricalStore

router = APIRouter(tags=["status"])


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def status(request: Request) -> dict:
    settings = get_settings_from_app(request)
    redis = request.app.state.redis
    redis_ok = "ok"
    try:
        await redis.ping()
    except Exception:
        redis_ok = "error"

    if not settings.resolved_asyncpg_dsn():
        database = "not_configured"
    else:
        h = request.app.state.historical_store
        if isinstance(h, PostgresHistoricalStore):
            database = "ok" if await h.ping() else "error"
        else:
            database = "not_configured"

    return {
        "ok": True,
        "service": "market_gateway",
        "redis": redis_ok,
        "database": database,
        "schwab_live_data_enabled": settings.enable_schwab_live_data,
        "schwab_backend": (
            "live"
            if getattr(request.app.state.schwab_client, "quote_source_label", None)
            == "live_schwab"
            else "stub"
        ),
        "real_trading_enabled": settings.enable_real_trading,
    }
