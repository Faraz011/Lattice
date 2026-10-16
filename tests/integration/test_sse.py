"""The live event stream stays open across quiet periods longer than the Redis socket timeout."""

import time
import uuid

from lattice.api.sse import case_events
from lattice.queue.events import EventStream


async def test_a_quiet_case_keeps_its_stream_open_past_the_socket_timeout(redis_client, keys):
    events = EventStream(redis_client, keys)
    case_id = f"case_sse{uuid.uuid4().hex[:12]}"
    stream = case_events(events, case_id)
    started = time.monotonic()

    chunks = []
    while time.monotonic() - started < 6:  # past redis-py's default 5 s socket timeout
        chunks.append(await anext(stream))
    await events.publish(case_id, "case_started", {"alert_id": "alert_x"})
    live = await anext(stream)

    assert chunks and set(chunks) == {": keep-alive\n\n"}
    assert "event: case_started" in live
    await stream.aclose()
