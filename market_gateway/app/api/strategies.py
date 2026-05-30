from fastapi import APIRouter, Depends, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.models import StrategyStatusResponse

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def strategies_status(request: Request) -> dict:
    _ = request
    return StrategyStatusResponse().model_dump(mode="json")


@router.post("/start", dependencies=[Depends(verify_api_key)])
async def strategies_start(request: Request) -> dict:
    _ = request
    return {"ok": True, "mode": "stub", "detail": "Strategy control not wired in Phase 1."}


@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def strategies_stop(request: Request) -> dict:
    _ = request
    return {"ok": True, "mode": "stub", "detail": "Strategy control not wired in Phase 1."}
