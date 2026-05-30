from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.models import DataMode
from market_gateway.app.deps import get_resolver

router = APIRouter(tags=["history"])


@router.get("/history/{symbol}", dependencies=[Depends(verify_api_key)])
async def history(
    request: Request,
    symbol: str = Path(...),
    timeframe: str = Query("1m"),
    start: datetime | None = None,
    end: datetime | None = None,
    lookback_days: int | None = None,
    mode: DataMode = Query(DataMode.CANONICAL_PLUS_LIVE),
) -> dict:
    data = await get_resolver(request).get_bars(
        symbol,
        timeframe,
        start=start,
        end=end,
        lookback_days=lookback_days,
        mode=mode,
    )
    return data.model_dump(mode="json")
