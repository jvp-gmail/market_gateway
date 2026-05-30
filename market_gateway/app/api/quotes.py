from fastapi import APIRouter, Depends, Query, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.deps import get_resolver

router = APIRouter(tags=["quotes"])


@router.get("/quotes", dependencies=[Depends(verify_api_key)])
async def get_quotes(
    request: Request,
    symbols: str = Query(..., description="Comma-separated equity symbols"),
) -> list:
    resolver = get_resolver(request)
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out = []
    for s in syms:
        out.append((await resolver.get_quote(s)).model_dump(mode="json"))
    return out
