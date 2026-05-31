import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import GatewayEvent
from market_gateway.app.core.time_utils import utc_now
from market_gateway.app.deps import get_event_bus

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/recent", dependencies=[Depends(verify_api_key)])
async def events_recent(
    request: Request,
    count: int = 100,
    bus: EventBus = Depends(get_event_bus),
) -> list:
    _ = request
    events = await bus.recent(count=count)
    return [e.model_dump(mode="json") for e in events]


@router.get("/stream", dependencies=[Depends(verify_api_key)])
async def events_stream(
    request: Request,
    bus: EventBus = Depends(get_event_bus),
):
    _ = request

    async def gen():
        hb = GatewayEvent(
            event_type="heartbeat",
            event_ts=None,
            received_ts=utc_now(),
            source="market_gateway",
            payload={"status": "starting"},
        )
        yield f"data: {hb.model_dump_json()}\n\n"
        try:
            async for ev in bus.stream_from():
                yield f"data: {ev.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
