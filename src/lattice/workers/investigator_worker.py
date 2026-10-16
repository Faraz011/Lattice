"""Investigator role: consume hypothesis jobs and publish one finding event per job.

Every job ends in a finding event, partial or failed included, so fan-in never waits on a
hypothesis that silently died. In single-agent mode the worker also enqueues verification.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from lattice.agents.investigator import OnEvent, investigate
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Finding, HypothesisBrief
from lattice.queue.jobs import Job
from lattice.queue.llm_cache import LLMCache
from lattice.queue.ratelimit import RateLimiter
from lattice.queue.streams import Handler

Investigate = Callable[[HypothesisBrief, OnEvent], Awaitable[Finding]]


class Publisher(Protocol):
    async def publish(self, case_id: str, event_type: str, data: dict[str, Any]) -> Any: ...


class Enqueuer(Protocol):
    async def enqueue(self, job: Job) -> Any: ...


def make_handler(run_investigation: Investigate, events: Publisher, queue: Enqueuer) -> Handler:
    async def handle(job: Job) -> None:
        brief = HypothesisBrief.model_validate(job.payload["brief"])
        await events.publish(job.case_id, "investigation_started",
                             {"job_id": job.job_id, "hypothesis": brief.hypothesis})

        async def on_event(kind: str, data: dict[str, Any]) -> None:
            await events.publish(job.case_id, kind, {**data, "hypothesis": brief.hypothesis})

        finding = await run_investigation(brief, on_event)
        dumped = finding.model_dump(mode="json")
        await events.publish(job.case_id, "finding", {"job_id": job.job_id,
                                                      "hypothesis": brief.hypothesis,
                                                      "finding": dumped})
        if job.payload.get("single_agent"):
            await queue.enqueue(Job.new("verify", case_id=job.case_id,
                                        payload={"findings": [dumped]}))

    return handle


async def build_handler(ctx) -> Handler:
    """Wire the real runtime: MCP tools, shared rate limiter and response cache."""
    from lattice.queue.streams import JobQueue

    settings = ctx.settings
    runtime = AgentRuntime(
        settings,
        mcp_url=settings.mcp_url,
        limiter=RateLimiter(ctx.redis, ctx.keys.limiter(), settings.llm_requests_per_minute,
                            settings.llm_requests_per_day),
        cache=LLMCache(ctx.redis, ctx.keys, settings.llm_cache_ttl_s, settings.llm_cache_enabled),
    )

    async def run_investigation(brief: HypothesisBrief, on_event: OnEvent) -> Finding:
        return await investigate(runtime, brief, on_event=on_event)

    return make_handler(run_investigation, ctx.events, JobQueue(ctx.redis, ctx.keys))
