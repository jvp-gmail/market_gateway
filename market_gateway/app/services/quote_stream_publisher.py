"""Publish quote snapshots to the Redis-backed event bus (Phase 4 streaming, part 1)."""

from __future__ import annotations

from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import (
    GatewayEvent,
    OptionContractQuote,
    QuoteSnapshot,
    StreamEventType,
)


async def publish_equity_quote(bus: EventBus, snap: QuoteSnapshot) -> str:
    """Emit one equity quote event. Payload shape: ``{"quote": {...}}`` (JSON-serializable)."""
    ev = GatewayEvent(
        event_type=StreamEventType.EQUITY_QUOTE,
        event_ts=snap.event_ts,
        received_ts=snap.received_ts,
        source=snap.source,
        payload={"quote": snap.model_dump(mode="json")},
    )
    return await bus.publish(ev)


async def publish_option_quote(bus: EventBus, quote: OptionContractQuote) -> str:
    """Emit one option contract quote event. Payload shape: ``{"quote": {...}}``."""
    ev = GatewayEvent(
        event_type=StreamEventType.OPTION_QUOTE,
        event_ts=quote.event_ts,
        received_ts=quote.received_ts,
        source=quote.source,
        payload={"quote": quote.model_dump(mode="json")},
    )
    return await bus.publish(ev)
