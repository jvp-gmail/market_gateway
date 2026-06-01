import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from market_gateway.app.auth import verify_api_key
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import GatewayEvent
from market_gateway.app.core.stream_symbols import StreamSymbolsPayload
from market_gateway.app.core.time_utils import utc_now
from market_gateway.app.deps import get_event_bus, get_stream_symbol_replace_queue

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


@router.put("/stream/symbols", dependencies=[Depends(verify_api_key)])
async def put_stream_symbols(
    request: Request,
    body: StreamSymbolsPayload,
    replace_queue: asyncio.Queue[StreamSymbolsPayload] = Depends(get_stream_symbol_replace_queue),
) -> StreamSymbolsPayload:
    """Replace Schwab LEVELONE equity/futures keys on the existing WebSocket session (no reconnect)."""
    _ = request
    if body.options:
        raise HTTPException(
            status_code=501,
            detail="LEVELONE_OPTIONS streaming is not implemented yet; send an empty options list.",
        )
    if not body.equities and not body.futures:
        raise HTTPException(
            status_code=400,
            detail="At least one of equities or futures must be non-empty (options-only is not supported yet).",
        )
    await replace_queue.put(body.model_copy())
    return body
