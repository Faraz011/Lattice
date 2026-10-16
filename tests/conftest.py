"""Shared fixtures. Service-backed fixtures only start when a test asks for them."""

import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from lattice.config import load_settings
from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.graph.client import GraphClient
from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema

TESTS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Mark tests by folder so `pytest -m unit` and `-m integration` select them."""
    for item in items:
        folder = Path(item.fspath).relative_to(TESTS_DIR).parts[0]
        if folder in ("unit", "integration", "live"):
            item.add_marker(getattr(pytest.mark, folder))


def serve_in_thread(app):
    """Run an ASGI app on a free local port; returns (base_url, stop)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        assert time.time() < deadline, "server did not start"
        time.sleep(0.05)

    def stop():
        server.should_exit = True
        thread.join(timeout=10)

    return f"http://127.0.0.1:{port}", stop


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


@pytest.fixture(scope="session")
def mcp_server_url(fixture_world):
    """The real Lattice MCP server over Streamable HTTP, backed by the fixture world."""
    from lattice.mcp_server.server import build_app

    base, stop = serve_in_thread(build_app())
    yield f"{base}/mcp"
    stop()
