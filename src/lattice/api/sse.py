"""Server-sent events: a case's event stream from the start (or a given ID), then live."""

import json
from collections.abc import AsyncIterator

from lattice.queue.events import EventStream

BLOCK_MS = 15_000


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
