from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from market_gateway.app.core.models import GatewayEvent
from market_gateway.app.core.time_utils import utc_now

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = logging.getLogger(__name__)


class EventBus:
    def __init__(
        self,
        redis: Redis,
        stream_name: str,
        *,
        xread_block_ms: int = 5000,
    ) -> None:
        self._redis = redis
        self._stream = stream_name
        self._xread_block_ms = xread_block_ms

    async def publish(self, event: GatewayEvent) -> str:
        payload = event.model_dump(mode="json")
        # JSON-serialize datetimes in nested payload
        data: dict[str, str] = {
            "data": json.dumps(payload, default=str),
        }
        msg_id = await self._redis.xadd(self._stream, data)
        return str(msg_id)

    async def recent(self, count: int = 100) -> list[GatewayEvent]:
        rows = await self._redis.xrevrange(self._stream, count=count)
        out: list[GatewayEvent] = []
        for _id, fields in rows:
            raw = fields.get(b"data", fields.get("data"))
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                d = json.loads(raw)
                out.append(GatewayEvent.model_validate(d))
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("skip bad stream entry: %s", e)
        return list(reversed(out))

    async def stream_from(self, last_id: str = "$") -> AsyncIterator[GatewayEvent]:
        current = last_id
        while True:
            resp = await self._redis.xread(
                {self._stream: current}, count=10, block=self._xread_block_ms
            )
            if not resp:
                yield GatewayEvent(
                    event_type="heartbeat",
                    event_ts=None,
                    received_ts=utc_now(),
                    source="market_gateway",
                    payload={"note": "idle"},
                )
                continue
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    current = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                    raw = fields.get(b"data", fields.get("data"))
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    if not raw:
                        continue
                    try:
                        d = json.loads(raw)
                        yield GatewayEvent.model_validate(d)
                    except (json.JSONDecodeError, ValueError):
                        continue
