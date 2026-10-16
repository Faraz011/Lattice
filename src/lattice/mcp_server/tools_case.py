"""Case tools: cite ledgered evidence and propose actions. Nothing here executes an action (R17)."""

from lattice.cases.policy import ACTION_TIERS, ActionKind
from lattice.graph.client import GraphClient
from lattice.ids import new_id
from lattice.mcp_server.ledger import ToolResult
from lattice.mcp_server.tools_graph import NotFound, label_for


class CitationResult(ToolResult):
    claim: str
    cited_result_ids: list[str]
    rejected_ids: list[str]


async def cite(
    graph: GraphClient,
    case_id: str,
    claim: str,
    result_ids: list[str],
    rel_ids: list[str] | None = None,
    node_ids: list[str] | None = None,
) -> CitationResult:
    """Attach evidence to a claim. Only IDs that the cited ledger entries returned are kept."""
    rows = await graph.read(
        """
        MATCH (l:LedgerEntry) WHERE l.case_id = $case_id AND l.result_id IN $result_ids
        RETURN l.result_id AS result_id, l.node_ids AS node_ids, l.rel_ids AS rel_ids
        """,
        case_id=case_id,
        result_ids=result_ids,
    )
    seen_nodes = {n for r in rows for n in r["node_ids"]}
    seen_rels = {r_id for r in rows for r_id in r["rel_ids"]}
    rel_ids, node_ids = rel_ids or [], node_ids or []
    return CitationResult(
        claim=claim,
        cited_result_ids=sorted(r["result_id"] for r in rows),
        rejected_ids=[i for i in rel_ids if i not in seen_rels]
        + [i for i in node_ids if i not in seen_nodes],
        rel_ids=[i for i in rel_ids if i in seen_rels],
        node_ids=[i for i in node_ids if i in seen_nodes],
    )


class ProposalResult(ToolResult):
    action_id: str
    kind: str
    tier: int
    status: str


async def propose_action(
    graph: GraphClient, case_id: str, kind: ActionKind, target_id: str, rationale: str
) -> ProposalResult:
    """Record a proposed action. Execution happens elsewhere, only after human approval."""
    if kind not in ACTION_TIERS:
        raise ValueError(f"unknown action kind {kind!r}")
    label = label_for(target_id)
    rows = await graph.read(f"MATCH (n:{label} {{id: $id}}) RETURN count(n) AS n", id=target_id)
    if rows[0]["n"] == 0:
        raise NotFound(f"no {label} with id {target_id}")

    action_id = new_id("action")
    tier = ACTION_TIERS[kind]
    await graph.write(
        """
        CREATE (:Action {
          id: $id, case_id: $case_id, kind: $kind, tier: $tier, status: 'proposed',
          target_id: $target_id, rationale: $rationale, created_at: datetime()
        })
        """,
        id=action_id,
        case_id=case_id,
        kind=kind,
        tier=tier,
        target_id=target_id,
        rationale=rationale,
    )
    return ProposalResult(
        action_id=action_id, kind=kind, tier=tier, status="proposed", node_ids=[target_id]
    )
