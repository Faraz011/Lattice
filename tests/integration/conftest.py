import uuid

import pytest
import redis.asyncio as redis

from lattice.config import load_settings
from lattice.queue.jobs import Keys


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
