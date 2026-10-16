"""Prepare a database for a demo: load a synthetic world and the committed replay recordings.

Safe to run on every deploy with `if_empty`: a database that already holds alerts keeps its data,
and recordings are upserted by case ID, so importing them twice changes nothing.
"""

from lattice.config import load_settings
from lattice.datagen.cli import _load_and_verify
from lattice.datagen.generator import DEMO_SEED, FIXTURE_SEED, generate_world
from lattice.graph.client import GraphClient
from lattice.graph.schema import apply_schema
from lattice.queue.replay import RECORDINGS_DIR, import_recording


async def seed(world_name: str = "demo", *, if_empty: bool = False) -> int:
    async with GraphClient.from_settings(load_settings()) as graph:
        await apply_schema(graph)
        alerts = (await graph.read("MATCH (a:Alert) RETURN count(a) AS n"))[0]["n"]

    status = 0
    if if_empty and alerts:
        print(f"database already holds {alerts} alerts; world not loaded")
    else:
        seed_value = DEMO_SEED if world_name == "demo" else FIXTURE_SEED
        status = await _load_and_verify(generate_world(seed_value, world_name), wipe=False)

    async with GraphClient.from_settings(load_settings()) as graph:
        paths = sorted(RECORDINGS_DIR.glob("*.json"))
        for path in paths:
            await import_recording(graph, path)
        print(f"imported {len(paths)} replay recordings")
    return status
