"""Investigator role: consume hypothesis jobs and publish one finding event per job.

Every job ends in a finding event, partial or failed included, so fan-in never waits on a
hypothesis that silently died. Then the finding moves on:
- single-agent mode: straight to the verifier;
- orchestrated mode: into the case's fan-in, and to the verifier when the set is complete.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from lattice.agents.investigator import OnEvent, investigate
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Finding, HypothesisBrief
from lattice.cases.dispatch import Enqueuer, hand_off_to_verifier
from lattice.queue.jobs import Job
from lattice.queue.llm_cache import LLMCache
from lattice.queue.ratelimit import RateLimiter
from lattice.queue.streams import Handler

Investigate = Callable[[HypothesisBrief, OnEvent], Awaitable[Finding]]
SaveFindings = Callable[[str, list[Finding]], Awaitable[None]]
Touch = Callable[[str], Awaitable[None]]
TOUCH_EVERY_S = 30


class Publisher(Protocol):
    async def publish(self, case_id: str, event_type: str, data: dict[str, Any]) -> Any: ...


class FanInRecorder(Protocol):
    async def record(self, case_id: str, hypothesis: str, finding: Finding) -> bool: ...
    async def collect(self, case_id: str) -> list[Finding]: ...


def make_handler(
    run_investigation: Investigate,
    events: Publisher,
    queue: Enqueuer,
    *,
    fanin: FanInRecorder | None = None,
    save_findings: SaveFindings | None = None,
    worker: str | None = None,
    touch: Touch | None = None,
    touch_every_s: float = TOUCH_EVERY_S,
) -> Handler:
    async def handle(job: Job) -> None:
        brief = HypothesisBrief.model_validate(job.payload["brief"])
        started = {"job_id": job.job_id, "hypothesis": brief.hypothesis}
        if worker:
            started["worker"] = worker
        await events.publish(job.case_id, "investigation_started", started)

        # A case that is being worked on must not look stalled to the sweeper, however long
        # the rate limiter makes the investigation take.
        last_touch = float("-inf")

        async def keep_alive() -> None:
            nonlocal last_touch
            if touch is not None and time.monotonic() - last_touch >= touch_every_s:
                last_touch = time.monotonic()
                await touch(job.case_id)

        await keep_alive()

        async def on_event(kind: str, data: dict[str, Any]) -> None:
            await keep_alive()
            await events.publish(job.case_id, kind, {**data, "hypothesis": brief.hypothesis})

        finding = await run_investigation(brief, on_event)
        await events.publish(job.case_id, "finding", {"job_id": job.job_id,
                                                      "hypothesis": brief.hypothesis,
                                                      "finding": finding.model_dump(mode="json")})
        if job.payload.get("single_agent"):
            await hand_off_to_verifier(save_findings, queue, job.case_id, [finding])
        elif fanin is not None and await fanin.record(job.case_id, brief.hypothesis, finding):
            findings = await fanin.collect(job.case_id)
            await hand_off_to_verifier(save_findings, queue, job.case_id, findings)

    return handle


async def build_handler(ctx) -> Handler:
    """Wire the real runtime: MCP tools, shared rate limiter and response cache."""
    from lattice.cases.store import CaseStore
    from lattice.graph.client import GraphClient
    from lattice.queue.fanin import FanIn
    from lattice.queue.streams import JobQueue

    settings = ctx.settings
    runtime = AgentRuntime(
        settings,
        mcp_url=settings.mcp_url,
        limiter=RateLimiter(ctx.redis, ctx.keys.limiter(), settings.llm_requests_per_minute,
                            settings.llm_requests_per_day),
        cache=LLMCache(ctx.redis, ctx.keys, settings.llm_cache_ttl_s, settings.llm_cache_enabled),
    )
    store = CaseStore(GraphClient.from_settings(settings))

    async def run_investigation(brief: HypothesisBrief, on_event: OnEvent) -> Finding:
        return await investigate(runtime, brief, on_event=on_event)

    return make_handler(run_investigation, ctx.events, JobQueue(ctx.redis, ctx.keys),
                        fanin=FanIn(ctx.redis, ctx.keys), save_findings=store.save_findings,
                        worker=ctx.worker_name, touch=store.touch)
