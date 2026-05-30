from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.models import OptionChainRequest
from market_gateway.app.deps import get_resolver

router = APIRouter(prefix="/options", tags=["options"])


@router.get("/chains", dependencies=[Depends(verify_api_key)])
async def option_chains(
    request: Request,
    symbol: str = Query(...),
    expiration: date | None = None,
    from_date: date | None = Query(None, alias="from_date"),
    to_date: date | None = Query(None, alias="to_date"),
    strike_count: int | None = None,
    contract_type: Literal["ALL", "CALL", "PUT"] = "ALL",
    include_quotes: bool = True,
) -> dict:
    req = OptionChainRequest(
        symbol=symbol,
        contract_type=contract_type,
        expiration=expiration,
        from_date=from_date,
        to_date=to_date,
        strike_count=strike_count,
        include_quotes=include_quotes,
    )
    chain = await get_resolver(request).get_option_chain(req)
    return chain.model_dump(mode="json")


@router.get("/quotes", dependencies=[Depends(verify_api_key)])
async def option_quotes(
    request: Request,
    symbols: str = Query(..., description="Comma-separated option symbols"),
) -> list:
    resolver = get_resolver(request)
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    out = []
    for s in syms:
        out.append((await resolver.get_option_quote(s)).model_dump(mode="json"))
    return out
