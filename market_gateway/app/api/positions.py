from fastapi import APIRouter, Depends, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.models import PositionRow
from market_gateway.schwab.client import StubSchwabClient

router = APIRouter(tags=["positions"])


@router.get("/positions", dependencies=[Depends(verify_api_key)])
async def positions(request: Request) -> list:
    schwab: StubSchwabClient = request.app.state.schwab_client
    raw = await schwab.get_positions()
    rows = []
    for p in raw.get("positions") or []:
        rows.append(
            PositionRow(
                symbol=str(p.get("symbol", "")),
                quantity=float(p.get("quantity", 0)),
                avg_price=float(p["averagePrice"]) if p.get("averagePrice") is not None else None,
            ).model_dump(mode="json")
        )
    return rows
