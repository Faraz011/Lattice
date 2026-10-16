"""Durable replay recordings: events copied from Redis into Neo4j and out to JSON files."""

import uuid

import pytest

from lattice.queue.events import EventStream
from lattice.queue.replay import (
    export_recording,
    import_recording,
    load_recording,
    replay,
    save_recording,
)


@pytest.fixture
async def case(redis_client, keys, graph):
    case_id = f"case_rec{uuid.uuid4().hex[:12]}"
    events = EventStream(redis_client, keys)
    await events.publish(case_id, "case_started", {"alert_id": "alert_1"})
    await events.publish(case_id, "tool_called", {"tool": "graph_neighbors", "result_id": "led_1"})
    await events.publish(case_id, "finding", {"hypothesis": "fan_out", "verdict": "supports"})
    await events.publish(case_id, "verdict", {"label": "fan_out", "score": 0.82})
    yield case_id
    await graph.write("MATCH (r:Recording {case_id: $c}) DELETE r", c=case_id)


async def collect(case_id, graph):
    return [(e.type, e.data) async for e in replay(await load_recording(graph, case_id), speed=0)]


async def test_replaying_a_recorded_case_emits_its_events_in_order(case, redis_client, keys, graph):
    live = await EventStream(redis_client, keys).read_all(case)
    await save_recording(graph, EventStream(redis_client, keys), case)

    replayed = await collect(case, graph)

    assert replayed == [(e.type, e.data) for e in live]
    assert [t for t, _ in replayed] == ["case_started", "tool_called", "finding", "verdict"]


async def test_a_saved_recording_still_replays_after_redis_is_flushed(case, redis_client, keys,
                                                                      graph):
    await save_recording(graph, EventStream(redis_client, keys), case)
    before = await collect(case, graph)

    await redis_client.delete(keys.events(case))
    assert await EventStream(redis_client, keys).read_all(case) == []

    assert await collect(case, graph) == before


async def test_export_then_import_into_an_empty_database_replays_identically(case, redis_client,
                                                                            keys, graph, tmp_path):
    await save_recording(graph, EventStream(redis_client, keys), case)
    before = await collect(case, graph)

    path = await export_recording(graph, case, tmp_path)
    await graph.write("MATCH (r:Recording {case_id: $c}) DELETE r", c=case)
    assert await load_recording(graph, case) == []
    await import_recording(graph, path)

    assert path.name == f"{case}.json"
    assert await collect(case, graph) == before


async def test_saving_twice_replaces_the_recording_rather_than_duplicating_it(case, redis_client,
                                                                              keys, graph):
    events = EventStream(redis_client, keys)
    await save_recording(graph, events, case)
    await events.publish(case, "action_executed", {"action_id": "act_1"})
    await save_recording(graph, events, case)

    rows = await graph.read("MATCH (r:Recording {case_id: $c}) RETURN count(r) AS n", c=case)
    assert rows[0]["n"] == 1
    assert (await collect(case, graph))[-1][0] == "action_executed"
