import pytest

from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import GatewayEvent
from market_gateway.app.core.time_utils import utc_now
from fakeredis.aioredis import FakeRedis


@pytest.mark.asyncio
async def test_event_bus_publish_and_recent() -> None:
    fake = FakeRedis(decode_responses=True)
    bus = EventBus(fake, "stream:test_events", xread_block_ms=10)
    await bus.publish(
        GatewayEvent(
            event_type="quote",
            event_ts=None,
            received_ts=utc_now(),
            source="test",
            payload={"symbol": "SPY"},
        )
    )
    recent = await bus.recent(count=10)
    assert len(recent) == 1
    assert recent[0].event_type == "quote"
    assert recent[0].payload["symbol"] == "SPY"
