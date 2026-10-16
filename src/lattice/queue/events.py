"""Per-case event streams: the live progress the API relays to the UI over SSE (KTD3)."""

import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis
from pydantic import BaseModel

from lattice.queue.jobs import Keys

EVENTS_TTL_S = 7 * 24 * 3600


class Event(BaseModel):
    id: str
    case_id: str
    type: str
    data: dict[str, Any]
    ts: datetime


class EventStream:
    def __init__(self, client: redis.Redis, keys: Keys) -> None:
        self._redis = client
        self._keys = keys

    async def publish(self, case_id: str, event_type: str, data: dict[str, Any]) -> str:
        key = self._keys.events(case_id)
        fields = {
            "type": event_type,
            "data": json.dumps(data, default=str),
            "ts": datetime.now(UTC).isoformat(),
        }
        event_id = await self._redis.xadd(key, fields)
        await self._redis.expire(key, EVENTS_TTL_S)
        return event_id

    async def read(
        self, case_id: str, after: str = "0-0", block_ms: int | None = None
    ) -> list[Event]:
        """Events after `after`; with `block_ms`, wait that long for at least one."""
        key = self._keys.events(case_id)
        response = await self._redis.xread({key: after}, block=block_ms)
        return [self._event(case_id, i, f) for _, entries in response for i, f in entries]

    async def read_all(self, case_id: str) -> list[Event]:
        entries = await self._redis.xrange(self._keys.events(case_id))
        return [self._event(case_id, i, f) for i, f in entries]

    @staticmethod
    def _event(case_id: str, event_id: str, fields: dict[str, str]) -> Event:
        return Event(
            id=event_id,
            case_id=case_id,
            type=fields["type"],
            data=json.loads(fields["data"]),
            ts=datetime.fromisoformat(fields["ts"]),
        )
