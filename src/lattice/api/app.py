"""The Lattice API: alerts, cases, live events and approvals.

    uvicorn lattice.api.app:app --port 8080
"""

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
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
from lattice.queue.ratelimit import RateLimiter
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

    @app.get("/budget")
    async def budget(request: Request) -> dict:
        """The shared model budget and the daily case cap, as the evaluation tools read them."""
        api: ApiState = request.app.state.api
        limiter = RateLimiter(api.redis, api.keys.limiter(), api.settings.llm_requests_per_minute,
                              api.settings.llm_requests_per_day)
        counts = await api.cases.counts()
        return {"per_minute": api.settings.llm_requests_per_minute,
                "per_day": api.settings.llm_requests_per_day,
                "remaining_today": await limiter.remaining_today(),
                "max_cases_per_day": api.settings.max_cases_per_day,
                "cases_today": counts["today"],
                "case_room": max(0, api.settings.max_cases_per_day - counts["today"])}

    return app


def __getattr__(name: str):
    # `uvicorn lattice.api.app:app` builds the app on first access, with settings from .env.
    if name == "app":
        return create_app()
    raise AttributeError(name)
