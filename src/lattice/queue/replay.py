"""Durable replay recordings (KTD2, KTD5).

A case's live events live in Redis, which may lose them on restart. Saving a recording copies
them into a `Recording` node in Neo4j, with an optional snapshot of the case and its evidence
graph so a replay needs nothing else. Exporting writes a JSON file under `recordings/` that can
be committed and imported into a fresh database, so the demo-day fallback survives both.

    python -m lattice.queue.replay save <case_id>
    python -m lattice.queue.replay export <case_id>
    python -m lattice.queue.replay import recordings/<case_id>.json
"""

import argparse
import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import redis.asyncio as redis

from lattice.config import load_settings
from lattice.graph.client import GraphClient
from lattice.ids import new_id
from lattice.queue.events import Event, EventStream
from lattice.queue.jobs import Keys

# The repo's `recordings/` in a checkout; the image sets LATTICE_RECORDINGS_DIR, because an
# installed package does not live inside the repo.
RECORDINGS_DIR = Path(
    os.environ.get("LATTICE_RECORDINGS_DIR") or Path(__file__).resolve().parents[3] / "recordings"
)


async def save_recording(
    graph: GraphClient, events: EventStream, case_id: str, snapshot: dict | None = None
) -> str:
    """Copy the case's current event stream into its (single) Recording node."""
    recorded = await events.read_all(case_id)
    return await _store(graph, case_id, [e.model_dump(mode="json") for e in recorded], snapshot)


async def _store(
    graph: GraphClient, case_id: str, events: list[dict], snapshot: dict | None = None
) -> str:
    rows = await graph.write(
        """
        MERGE (r:Recording {case_id: $case_id})
        ON CREATE SET r.id = $id
        SET r.events_json = $events_json, r.event_count = $count, r.recorded_at = datetime(),
            r.snapshot_json = coalesce($snapshot_json, r.snapshot_json),
            r.alert_id = coalesce($alert_id, r.alert_id)
        RETURN r.id AS id
        """,
        case_id=case_id,
        # Kept on the recording itself, so an imported replay lists under its alert even in a
        # fresh database that has no Case records.
        alert_id=((snapshot or {}).get("case") or {}).get("alert_id"),
        id=new_id("recording"),
        events_json=json.dumps(events),
        count=len(events),
        snapshot_json=json.dumps(snapshot, default=str) if snapshot is not None else None,
    )
    return rows[0]["id"]


async def load_snapshot(graph: GraphClient, case_id: str) -> dict | None:
    rows = await graph.read(
        "MATCH (r:Recording {case_id: $case_id}) RETURN r.snapshot_json AS snapshot",
        case_id=case_id,
    )
    return json.loads(rows[0]["snapshot"]) if rows and rows[0]["snapshot"] else None


async def load_recording(graph: GraphClient, case_id: str) -> list[Event]:
    rows = await graph.read(
        "MATCH (r:Recording {case_id: $case_id}) RETURN r.events_json AS events",
        case_id=case_id,
    )
    if not rows:
        return []
    return [Event.model_validate(e) for e in json.loads(rows[0]["events"])]


async def replay(events: list[Event], speed: float = 1.0) -> AsyncIterator[Event]:
    """Yield events in their original order; `speed` > 0 reproduces their pacing, scaled."""
    previous = None
    for event in events:
        if speed > 0 and previous is not None:
            gap = (event.ts - previous.ts).total_seconds() / speed
            await asyncio.sleep(max(0.0, min(gap, 5.0)))
        previous = event
        yield event


async def export_recording(graph: GraphClient, case_id: str, directory: Path) -> Path:
    events = await load_recording(graph, case_id)
    if not events:
        raise LookupError(f"no recording saved for {case_id}")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case_id}.json"
    payload = {"case_id": case_id, "events": [e.model_dump(mode="json") for e in events],
               "snapshot": await load_snapshot(graph, case_id)}
    path.write_text(json.dumps(payload, indent=1) + "\n")
    return path


async def import_recording(graph: GraphClient, path: Path) -> str:
    payload = json.loads(path.read_text())
    return await _store(graph, payload["case_id"], payload["events"], payload.get("snapshot"))


async def _cli(args: argparse.Namespace) -> None:
    settings = load_settings()
    async with GraphClient.from_settings(settings) as graph:
        if args.command == "save":
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            events = EventStream(client, Keys(settings.redis_namespace))
            print(await save_recording(graph, events, args.target))
            await client.aclose()
        elif args.command == "export":
            print(await export_recording(graph, args.target, RECORDINGS_DIR))
        else:
            print(await import_recording(graph, Path(args.target)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="lattice.queue.replay")
    parser.add_argument("command", choices=["save", "export", "import"])
    parser.add_argument("target", help="case ID, or a recording file for import")
    asyncio.run(_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
