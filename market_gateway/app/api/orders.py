from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.cache_keys import order_preview_key
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import (
    GatewayEvent,
    OrderPreviewRequest,
    OrderPreviewResponse,
    OrderSubmitRequest,
    OrderSubmitResponse,
)
from market_gateway.app.core.time_utils import utc_now
from market_gateway.app.deps import get_event_bus, get_redis, get_settings_from_app

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/open", dependencies=[Depends(verify_api_key)])
async def orders_open() -> list:
    return []


@router.post("/preview", dependencies=[Depends(verify_api_key)])
async def orders_preview(
    request: Request,
    body: OrderPreviewRequest,
    bus: EventBus = Depends(get_event_bus),
) -> OrderPreviewResponse:
    redis = get_redis(request)
    schwab: Any = request.app.state.schwab_client
    raw = await schwab.preview_order(body.model_dump())
    preview_id = str(uuid.uuid4())
    payload = {
        "symbol": body.symbol,
        "side": body.side,
        "quantity": body.quantity,
        "order_type": body.order_type,
        "raw": raw,
    }
    await redis.set(order_preview_key(preview_id), json.dumps(payload), ex=300)
    ev = GatewayEvent(
        event_type="order_preview",
        event_ts=None,
        received_ts=utc_now(),
        source="market_gateway",
        payload={"preview_id": preview_id, **payload},
    )
    await bus.publish(ev)
    return OrderPreviewResponse(
        preview_id=preview_id,
        symbol=body.symbol,
        side=body.side,
        quantity=body.quantity,
        mode="paper",
        estimated_notional=float(raw.get("estimatedNotional") or 0),
    )


@router.post("/submit", dependencies=[Depends(verify_api_key)])
async def orders_submit(
    request: Request,
    body: OrderSubmitRequest,
    bus: EventBus = Depends(get_event_bus),
) -> OrderSubmitResponse:
    settings = get_settings_from_app(request)
    redis = get_redis(request)
    _ = settings  # Phase 6: gate real broker on enable_real_trading
    raw_prev = await redis.get(order_preview_key(body.preview_id))
    if not raw_prev:
        raise HTTPException(status_code=400, detail="Invalid or expired preview_id")

    schwab: Any = request.app.state.schwab_client
    # Phase 1: never call real submit — stub only
    out = await schwab.submit_order(
        {
            "preview_id": body.preview_id,
            "symbol": body.symbol,
            "side": body.side,
            "quantity": body.quantity,
            "paper": True,
        }
    )
    ev = GatewayEvent(
        event_type="order_submit",
        event_ts=None,
        received_ts=utc_now(),
        source="paper_stub",
        payload={"preview_id": body.preview_id, "response": out},
    )
    await bus.publish(ev)
    return OrderSubmitResponse(
        order_id=str(out.get("orderId") or "paper-stub"),
        status="accepted",
        mode="paper",
        message="Stub order accepted; no broker submission in Phase 1.",
    )


@router.post("/cancel", dependencies=[Depends(verify_api_key)])
async def orders_cancel(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    _ = request, body
    return {"ok": True, "mode": "paper", "detail": "stub cancel"}
