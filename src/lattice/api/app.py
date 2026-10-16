"""The Lattice API: alerts, cases, live events and approvals.

    uvicorn lattice.api.app:app --port 8080
"""

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lattice.api import routes_actions, routes_alerts, routes_cases
from lattice.api.state import ApiState
from lattice.cases.actions import ActionStore
from lattice.cases.store import CaseStore
from lattice.config import Settings, load_settings
from lattice.graph.client import GraphClient
from lattice.graph.schema import apply_schema
from lattice.queue.events import EventStream
from lattice.queue.jobs import Keys
from lattice.queue.streams import JobQueue


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with GraphClient.from_settings(resolved) as graph:
            await apply_schema(graph)
            client = redis.Redis.from_url(resolved.redis_url, decode_responses=True)
            keys = Keys(resolved.redis_namespace)
            app.state.api = ApiState(
                settings=resolved,
                graph=graph,
                redis=client,
                keys=keys,
                events=EventStream(client, keys),
                queue=JobQueue(client, keys),
                cases=CaseStore(graph),
                actions=ActionStore(graph),
            )
            try:
                yield
            finally:
                await client.aclose()

    app = FastAPI(title="Lattice", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Approver-Token", "X-Approver-Name", "Last-Event-ID"],
    )
    app.include_router(routes_alerts.router)
    app.include_router(routes_cases.router)
    app.include_router(routes_actions.router)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app


def __getattr__(name: str):
    # `uvicorn lattice.api.app:app` builds the app on first access, with settings from .env.
    if name == "app":
        return create_app()
    raise AttributeError(name)
