import asyncio

import pytest

from lattice.config import load_settings
from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.graph.client import GraphClient
from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema


@pytest.fixture(scope="session")
def fixture_world():
    """The seed-7 fixture world, loaded into Neo4j once per test session (loading is idempotent)."""
    world = generate_world(seed=FIXTURE_SEED, size="fixture")

    async def load():
        async with GraphClient.from_settings(load_settings()) as graph:
            await apply_schema(graph)
            await load_batch(graph, world.batch)

    asyncio.run(load())
    return world


@pytest.fixture
async def graph():
    async with GraphClient.from_settings(load_settings()) as client:
        yield client
