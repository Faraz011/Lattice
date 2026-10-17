"""Verifier role: turn findings into the case's verdict and, when warranted, a proposal.

Steps for one verify job:
1. Move the case to `verifying` (skipping the job if the case is already past it).
2. Keep only claims whose citations are ledgered (R12) and still exist in the graph.
3. Score the cited evidence and decide the outcome with the findings (R15).
4. For a suspicious verdict: compute the blast radius and propose a tier 2-3 action (R16).
5. Save the case's replay recording.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from lattice.agents.narrator import Narrative, template_narrative
from lattice.agents.schemas import Finding
from lattice.cases.proposals import propose_for_case
from lattice.cases.store import CaseStore
from lattice.cases.views import record_case
from lattice.config import Settings
from lattice.explain.citations import check_against_ledger, load_ledger, reverify
from lattice.explain.llm_attribution import LLMAttribution, attribute_case
from lattice.explain.report import CircuitReport, build_report
from lattice.explain.verdict import Outcome, decide
from lattice.graph.client import GraphClient
from lattice.graph.subgraph import load_evidence
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.queue.streams import Handler
from lattice.scoring.scorer import Scorer

Narrate = Callable[[str, CircuitReport], Awaitable[Narrative]]
# (case, result_ids the kept claims cited, report) -> what the LLM's judgement leaned on.
Attribute = Callable[[dict[str, Any], list[str], CircuitReport], Awaitable[LLMAttribution]]

# How a case reaches `verifying` from wherever it is.
ROUTE_TO_VERIFYING = {
    "received": ["investigating", "verifying"],
    "planning": ["investigating", "verifying"],
    "investigating": ["verifying"],
    "verifying": [],
}


async def _template(case_id: str, report: CircuitReport) -> Narrative:
    return Narrative(text=template_narrative(report), source="template")


def make_handler(
    graph: GraphClient, events: EventStream, settings: Settings, narrate: Narrate = _template,
    attribute: Attribute | None = None,
) -> Handler:
    cases = CaseStore(graph)
    scorer = Scorer.from_settings(settings)

    async def handle(job: Job) -> None:
        case = await cases.get(job.case_id)
        if case["status"] not in ROUTE_TO_VERIFYING:
            return  # already verified (a redelivered job) or closed by a human
        for status in ROUTE_TO_VERIFYING[case["status"]]:
            await cases.transition(case["id"], status, "verifying findings")
        await events.publish(case["id"], "verification_started", {})

        findings = [Finding.model_validate(f) for f in job.payload["findings"]]
        claims = [c for f in findings for c in f.claims]
        kept, rejected = check_against_ledger(claims, await load_ledger(graph, case["id"]))
        kept, unverified = await reverify(graph, kept)

        cited = list(dict.fromkeys(r for c in kept for r in c.rel_ids))
        evidence = await load_evidence(graph, cited)
        score = scorer.score(evidence)
        outcome = decide(case["id"], findings, score, scorer.threshold, rejected, unverified,
                         kept)

        # Flagged verdicts carry the evidence circuit and its explanation (R13, R14).
        report = narrative = None
        if outcome.status != "closed_no_action":
            report = build_report(evidence, scorer)
            narrative = await narrate(case["id"], report)
            if outcome.status == "awaiting_approval" and attribute is not None:
                # A tier 2-3 action will be proposed: show what the LLM's judgement leaned on.
                cited = list(dict.fromkeys(r for c in kept for r in c.result_ids))
                report.llm_attribution = await attribute(case, cited, report)

        await graph.write(
            """
            MATCH (c:Case {id: $id})
            SET c.verdict = $verdict, c.circuit = $circuit, c.narrative = $narrative
            """,
            id=case["id"],
            verdict=outcome.verdict.model_dump_json(),
            circuit=report.model_dump_json() if report else None,
            narrative=narrative.model_dump_json() if narrative else None,
        )
        await events.publish(case["id"], "verdict", {
            "outcome": outcome.status,
            "verdict": outcome.verdict.model_dump(mode="json"),
            "score": {"score": score.score, "typology": score.typology,
                      "detectors": score.detectors, "reasons": score.reasons},
            "circuit": report.model_dump(mode="json") if report else None,
            "narrative": narrative.model_dump(mode="json") if narrative else None,
        })

        if outcome.status == "awaiting_approval":
            verdict = outcome.verdict
            await propose_for_case(graph, events, case, verdict, (
                f"{verdict.typology} pattern, risk {verdict.risk} (score {verdict.score:.2f}), "
                f"backed by {len(verdict.claims)} verified claims"))
        await cases.transition(case["id"], outcome.status, _reason(outcome, scorer.threshold))
        await record_case(graph, events, case["id"])  # every verdict can be replayed

    return handle


def _reason(outcome: Outcome, threshold: float) -> str:
    if outcome.verdict.review_reason:
        return outcome.verdict.review_reason
    if outcome.status == "closed_no_action":
        return (f"the cited evidence scores {outcome.verdict.score:.2f}, below the "
                f"{threshold:.2f} threshold")
    return f"{outcome.verdict.typology} pattern scores {outcome.verdict.score:.2f}"


async def build_handler(ctx) -> Handler:
    from lattice.agents.narrator import narrate
    from lattice.agents.provider import model_for_role
    from lattice.agents.runtime import AgentRuntime
    from lattice.agents.scripted import SCRIPTED
    from lattice.queue.llm_cache import LLMCache
    from lattice.queue.ratelimit import RateLimiter
    from lattice.queue.usage import UsageLedger

    settings = ctx.settings
    graph = GraphClient.from_settings(settings)  # lives as long as the worker process
    runtime = AgentRuntime(
        settings,
        mcp_url=None,  # the narrator and the judge work from what they are given
        limiter=RateLimiter(ctx.redis, ctx.keys.limiter(), settings.llm_requests_per_minute,
                            settings.llm_requests_per_day),
        cache=LLMCache(ctx.redis, ctx.keys, settings.llm_cache_ttl_s, settings.llm_cache_enabled),
        usage=UsageLedger(ctx.redis, ctx.keys),
    )

    async def narrate_case(case_id: str, report: CircuitReport) -> Narrative:
        return await narrate(runtime, case_id, report)

    async def attribute_verdict(case: dict[str, Any], cited: list[str],
                                report: CircuitReport) -> LLMAttribution:
        return await attribute_case(graph, runtime, case, cited, report.circuit.circuit_edges,
                                    settings.llm_attribution_samples,
                                    settings.llm_attribution_max_sources)

    scripted = model_for_role("narrator", settings) == SCRIPTED
    return make_handler(graph, ctx.events, settings,
                        _template if scripted else narrate_case,  # scripted: the template
                        attribute_verdict if settings.llm_attribution_samples else None)
