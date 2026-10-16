import asyncio
import uuid

import pytest
import redis.asyncio as redis

from lattice.config import load_settings
from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.graph.client import GraphClient
from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema
from lattice.queue.jobs import Keys


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


@pytest.fixture
def redis_url():
    return load_settings().redis_url


@pytest.fixture
async def redis_client(redis_url):
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def keys(redis_client):
    """A private key namespace per test; everything under it is deleted afterwards."""
    keys = Keys(f"test-{uuid.uuid4().hex[:10]}")
    yield keys
    async for key in redis_client.scan_iter(match=f"{keys.namespace}:*"):
        await redis_client.delete(key)
