"""Orchestrator role: plan an investigation and fan it out (R8, KTD11).

For one investigate job:
1. Move the case to `planning`.
2. Summarise the seed account structurally (one ledgered tool call; no free text).
3. Choose two to four hypotheses (one model call; catalog-only, with a default set).
4. Open the fan-in with a deadline, enqueue one hypothesis job per choice, and move the case
   to `investigating`.
The orchestrator never waits for findings. Investigators complete the fan-in themselves, and the
sweeper (which runs alongside this role) enforces the deadline.
"""

from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from lattice.cases.dispatch import Enqueuer
from lattice.graph.client import GraphClient
from lattice.mcp_server import tools_graph
from lattice.mcp_server.ledger import ToolContext, run_tool
from lattice.queue.jobs import Job
from lattice.queue.streams import Handler

Summarise = Callable[[dict[str, Any]], Awaitable[str]]
Choose = Callable[[dict[str, Any], str], Awaitable[list[str]]]

REPORTING_THRESHOLD = 10_000.0


def make_handler(cases, fanin, queue: Enqueuer, events, summarise: Summarise, choose: Choose,
                 *, deadline_s: float) -> Handler:
    async def handle(job: Job) -> None:
        case = await cases.get(job.case_id)
        status = case["status"]
        if status not in ("received", "planning", "investigating"):
            return
        if status == "investigating" and await fanin.exists(case["id"]):
            return  # already fanned out and still collecting
        if status == "received":
            await cases.transition(case["id"], "planning", "choosing hypotheses")

        summary = await summarise(case)
        hypotheses = await choose(case, summary)
        await events.publish(case["id"], "hypotheses_chosen",
                             {"hypotheses": hypotheses, "summary": summary})

        await fanin.open(case["id"], hypotheses, deadline_s)
        for hypothesis in hypotheses:
            brief = {
                "case_id": case["id"],
                "alert_id": case["alert_id"],
                "seed_account_id": case["seed_account_id"],
                "alert_reason": case.get("alert_reason") or "",
                "hypothesis": hypothesis,
            }
            await queue.enqueue(Job.new("hypothesis", case["id"],
                                        {"brief": brief, "single_agent": False}))
        if case["status"] != "investigating":
            await cases.transition(case["id"], "investigating",
                                   f"testing {', '.join(hypotheses)}")

    return handle


async def structural_summary(graph: GraphClient, case: dict[str, Any]) -> str:
    """Numbers only: counts, totals, ages and counterparty kinds around the seed account."""
    seed = case["seed_account_id"]
    result = await run_tool(
        ToolContext(graph=graph, case_id=case["id"]), "graph_neighbors",
        {"node_id": seed, "direction": "both", "hops": 1, "purpose": "orchestrator summary"},
        lambda: tools_graph.neighbors(graph, seed, direction="both", hops=1, limit=500),
    )
    nodes = {n.id: n for n in result.nodes}
    transfers = [r for r in result.rels if r.type == "TRANSFER"]
    inbound = [r for r in transfers if r.dst == seed]
    outbound = [r for r in transfers if r.src == seed]
    devices = [r for r in result.rels if r.type == "USED_DEVICE"]

    def kinds(rels, end: str) -> str:
        counts = Counter(nodes[getattr(r, end)].props.get("kind", "?") for r in rels
                         if getattr(r, end) in nodes)
        return ", ".join(f"{k}: {n}" for k, n in sorted(counts.items())) or "none"

    def side(label: str, rels, end: str) -> str:
        if not rels:
            return f"{label}: none"
        amounts = [r.props["amount"] for r in rels]
        return (f"{label}: {len(rels)} transfers, total {sum(amounts):,.2f}, largest "
                f"{max(amounts):,.2f}, {len({getattr(r, end) for r in rels})} counterparties "
                f"({kinds(rels, end)})")

    times = sorted(datetime.fromisoformat(r.props["ts"]) for r in transfers)
    span_days = (times[-1] - times[0]).total_seconds() / 86_400 if times else 0
    near_threshold = sum(1 for r in inbound
                         if 0.8 * REPORTING_THRESHOLD <= r.props["amount"] < REPORTING_THRESHOLD)
    seed_props = nodes[seed].props if seed in nodes else {}
    return "\n".join([
        f"- seed account kind: {seed_props.get('kind', '?')}, opened "
        f"{str(seed_props.get('created_at', '?'))[:10]}",
        f"- {side('inbound', inbound, 'src')}",
        f"- {side('outbound', outbound, 'dst')}",
        f"- activity spans {span_days:.1f} days",
        f"- inbound transfers between 8,000 and 10,000: {near_threshold}",
        f"- devices used: {len(devices)}",
    ])


async def build_handler(ctx) -> Handler:
    from lattice.agents.orchestrator import choose_hypotheses
    from lattice.agents.runtime import AgentRuntime
    from lattice.cases.store import CaseStore
    from lattice.queue.fanin import FanIn
    from lattice.queue.llm_cache import LLMCache
    from lattice.queue.ratelimit import RateLimiter
    from lattice.queue.streams import JobQueue
    from lattice.queue.usage import UsageLedger

    settings = ctx.settings
    graph = GraphClient.from_settings(settings)  # lives as long as the worker process
    runtime = AgentRuntime(
        settings,
        mcp_url=None,  # one structured choice, no tools
        limiter=RateLimiter(ctx.redis, ctx.keys.limiter(), settings.llm_requests_per_minute,
                            settings.llm_requests_per_day),
        cache=LLMCache(ctx.redis, ctx.keys, settings.llm_cache_ttl_s, settings.llm_cache_enabled),
        usage=UsageLedger(ctx.redis, ctx.keys),
    )

    async def summarise(case: dict[str, Any]) -> str:
        return await structural_summary(graph, case)

    async def choose(case: dict[str, Any], summary: str) -> list[str]:
        return await choose_hypotheses(runtime, case["id"], summary)

    return make_handler(CaseStore(graph), FanIn(ctx.redis, ctx.keys),
                        JobQueue(ctx.redis, ctx.keys), ctx.events, summarise, choose,
                        deadline_s=settings.hypothesis_deadline_s)
