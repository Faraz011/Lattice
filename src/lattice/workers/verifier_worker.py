"""Verifier role: turn findings into the case's verdict and, when warranted, a proposal.

Steps for one verify job:
1. Move the case to `verifying` (skipping the job if the case is already past it).
2. Keep only claims whose citations are ledgered (R12) and still exist in the graph.
3. Score the cited evidence and decide the outcome with the findings (R15).
4. For a suspicious verdict: compute the blast radius and propose a tier 2-3 action (R16).
"""

import json
from typing import Any

from lattice.agents.schemas import Finding
from lattice.cases.actions import ActionStore
from lattice.cases.store import CaseStore
from lattice.config import Settings
from lattice.explain.citations import check_against_ledger, load_ledger, reverify
from lattice.explain.verdict import Outcome, decide
from lattice.graph.client import GraphClient
from lattice.graph.subgraph import load_evidence
from lattice.mcp_server import tools_algo, tools_case
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.queue.streams import Handler
from lattice.scoring.scorer import Scorer

# How a case reaches `verifying` from wherever it is.
ROUTE_TO_VERIFYING = {
    "received": ["investigating", "verifying"],
    "planning": ["investigating", "verifying"],
    "investigating": ["verifying"],
    "verifying": [],
}


def make_handler(graph: GraphClient, events: EventStream, settings: Settings) -> Handler:
    cases, actions = CaseStore(graph), ActionStore(graph)
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
        score = scorer.score(await load_evidence(graph, cited))
        outcome = decide(case["id"], findings, score, scorer.threshold, rejected, unverified,
                         kept)

        await graph.write("MATCH (c:Case {id: $id}) SET c.verdict = $verdict",
                          id=case["id"], verdict=outcome.verdict.model_dump_json())
        await events.publish(case["id"], "verdict", {
            "outcome": outcome.status,
            "verdict": outcome.verdict.model_dump(mode="json"),
            "score": {"score": score.score, "typology": score.typology,
                      "detectors": score.detectors, "reasons": score.reasons},
        })

        if outcome.status == "awaiting_approval":
            await _propose(graph, actions, events, case, outcome)
        await cases.transition(case["id"], outcome.status,
                               outcome.verdict.review_reason or f"verdict: {outcome.status}")

    return handle


async def _propose(
    graph: GraphClient, actions: ActionStore, events: EventStream, case: dict[str, Any],
    outcome: Outcome,
) -> None:
    verdict = outcome.verdict
    kind = "freeze" if verdict.risk == "high" else "escalate"
    target = case["seed_account_id"]
    rationale = (f"{verdict.typology} pattern, risk {verdict.risk} (score {verdict.score:.2f}), "
                 f"backed by {len(verdict.claims)} verified claims")
    proposal = await tools_case.propose_action(graph, case["id"], kind, target, rationale)
    impact = await tools_algo.impact(graph, target, hops=2)
    blast_radius = {
        "hops": 2,
        "account_count": impact.account_count,
        "customer_count": impact.customer_count,
        "sample_accounts": impact.accounts[:20],
    }
    await actions.set_blast_radius(proposal.action_id, blast_radius)
    await events.publish(case["id"], "action_proposed", {
        "action_id": proposal.action_id, "kind": kind, "tier": proposal.tier,
        "target_id": target, "blast_radius": json.loads(json.dumps(blast_radius)),
    })


async def build_handler(ctx) -> Handler:
    graph = GraphClient.from_settings(ctx.settings)  # lives as long as the worker process
    return make_handler(graph, ctx.events, ctx.settings)
