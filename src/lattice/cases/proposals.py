"""The one place that proposes a case's tier 2-3 action, with its blast radius (R16).

Used by the verifier for suspicious verdicts and by the API when a reviewer escalates a case.
At most one proposal is open per case: a redelivered verify job, or an escalation of a case
that already has a proposal, reuses it instead of creating another.
"""

import json
from typing import Any

from lattice.agents.schemas import Verdict
from lattice.cases.actions import ActionStore
from lattice.graph.client import GraphClient
from lattice.mcp_server import tools_algo, tools_case

BLAST_RADIUS_HOPS = 2


async def blast_radius(graph: GraphClient, target: str) -> dict[str, Any]:
    impact = await tools_algo.impact(graph, target, hops=BLAST_RADIUS_HOPS)
    return {
        "hops": BLAST_RADIUS_HOPS,
        "account_count": impact.account_count,
        "customer_count": impact.customer_count,
        "sample_accounts": impact.accounts[:20],
    }


async def propose_for_case(
    graph: GraphClient, events: Any, case: dict[str, Any], verdict: Verdict | None,
    rationale: str,
) -> dict[str, Any]:
    """Return the case's open proposal, creating it (freeze for high risk, else escalate)."""
    actions = ActionStore(graph)
    open_ = [a for a in await actions.for_case(case["id"]) if a["status"] == "proposed"]
    if open_:
        action = open_[0]
        if not action.get("blast_radius"):
            await actions.set_blast_radius(action["id"],
                                           await blast_radius(graph, action["target_id"]))
            action = await actions.get(action["id"])
        return action

    kind = "freeze" if verdict is not None and verdict.risk == "high" else "escalate"
    target = case["seed_account_id"]
    proposal = await tools_case.propose_action(graph, case["id"], kind, target, rationale)
    radius = await blast_radius(graph, target)
    await actions.set_blast_radius(proposal.action_id, radius)
    await events.publish(case["id"], "action_proposed", {
        "action_id": proposal.action_id, "kind": kind, "tier": proposal.tier,
        "target_id": target, "blast_radius": json.loads(json.dumps(radius)),
    })
    return await actions.get(proposal.action_id)
