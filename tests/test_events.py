from fakeredis.aioredis import FakeRedis
import pytest

from market_gateway.app.core.event_bus import EventBus
from market_gateway.app.core.models import GatewayEvent, StreamEventType
from market_gateway.app.core.time_utils import utc_now


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


@pytest.mark.asyncio
async def test_ensure_stream_creates_key_when_missing() -> None:
    fake = FakeRedis(decode_responses=True)
    name = "stream:ensure_test"
    bus = EventBus(fake, name, xread_block_ms=10)
    assert await fake.type(name) == "none"
    await bus.ensure_stream_exists()
    assert await fake.type(name) == "stream"


@pytest.mark.asyncio
async def test_stream_from_survives_wrong_redis_key_type() -> None:
    """If EVENT_STREAM_NAME collides with a non-stream key, emit stream_error instead of crashing."""
    fake = FakeRedis(decode_responses=True)
    name = "stream:collision"
    await fake.set(name, "not-a-stream")
    bus = EventBus(fake, name, xread_block_ms=10)
    await bus.ensure_stream_exists()  # logs error, does not overwrite key
    it = bus.stream_from()
    first = await anext(it)
    assert first.event_type == StreamEventType.STREAM_ERROR
    assert first.payload.get("stage") == "xread"
