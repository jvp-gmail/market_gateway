"""Optional synthetic quote events for local SSE / stream testing (no Schwab socket)."""

from __future__ import annotations

import asyncio
import logging

from market_gateway.app.config import Settings
from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import QuoteSnapshot
from market_gateway.app.core.time_utils import utc_now
from market_gateway.app.services.quote_stream_publisher import publish_equity_quote

log = logging.getLogger(__name__)


def _parse_stub_symbols(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


async def run_quote_stream_stub(bus: EventBus, settings: Settings) -> None:
    """Loop: publish stub `equity_quote` events until cancelled (see `enable_quote_stream_stub`)."""
    syms = _parse_stub_symbols(settings.quote_stream_stub_symbols)
    if not syms:
        syms = ["/MES"]
    interval = max(0.5, float(settings.quote_stream_stub_interval_seconds))
    log.info(
        "quote stream stub enabled (%s every %.1fs); SSE clients can use GET /events/stream",
        ", ".join(syms),
        interval,
    )
    tick = 0
    try:
        while True:
            await asyncio.sleep(interval)
            now = utc_now()
            for sym in syms:
                base = 5_000.0 + (tick % 20) * 0.25 + hash(sym) % 100 * 0.01
                snap = QuoteSnapshot(
                    symbol=sym,
                    event_ts=now,
                    received_ts=now,
                    bid=round(base - 0.25, 2),
                    ask=round(base + 0.25, 2),
                    last=round(base, 2),
                    mark=round(base, 2),
                    bid_size=1,
                    ask_size=2,
                    volume=100 + tick,
                    source="quote_stream_stub",
                    raw=None,
                )
                await publish_equity_quote(bus, snap)
            tick += 1
    except asyncio.CancelledError:
        log.info("quote stream stub cancelled")
        raise
