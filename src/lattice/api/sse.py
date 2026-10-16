"""Server-sent events: a case's event stream from the start (or a given ID), then live."""

import json
from collections.abc import AsyncIterator

from lattice.queue.events import EventStream

# Each wait must end inside the Redis client's socket timeout (5 s by default in redis-py 8),
# or the read fails and the stream drops. A quiet case gets a keep-alive comment each wait.
BLOCK_MS = 3_000


async def case_events(events: EventStream, case_id: str, after: str = "0-0") -> AsyncIterator[str]:
    last = after
    while True:
        batch = await events.read(case_id, after=last, block_ms=BLOCK_MS)
        if not batch:
            yield ": keep-alive\n\n"
            continue
        for event in batch:
            last = event.id
            payload = json.dumps(event.model_dump(mode="json"))
            yield f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n"
