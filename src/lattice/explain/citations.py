"""Citation checks (R12): claims may cite only what tools returned, and only what still exists.

Two filters, in order:
1. Against the ledger: a claim citing any ID, or any result_id, that no tool call of this case
   returned is dropped whole, and the unknown IDs are reported.
2. Against the graph: a claim citing a transfer, device link or node that no longer exists is
   dropped, and those IDs are reported as unverified.
"""

from dataclasses import dataclass, field

from lattice.agents.schemas import Claim
from lattice.graph.client import GraphClient


@dataclass(frozen=True)
class Ledger:
    result_ids: set[str] = field(default_factory=set)
    node_ids: set[str] = field(default_factory=set)
    rel_ids: set[str] = field(default_factory=set)


async def load_ledger(graph: GraphClient, case_id: str) -> Ledger:
    rows = await graph.read(
        "MATCH (l:LedgerEntry {case_id: $case_id}) "
        "RETURN l.result_id AS result_id, l.node_ids AS node_ids, l.rel_ids AS rel_ids",
        case_id=case_id,
    )
    return Ledger(
        result_ids={r["result_id"] for r in rows},
        node_ids={n for r in rows for n in r["node_ids"]},
        rel_ids={e for r in rows for e in r["rel_ids"]},
    )


def check_against_ledger(claims: list[Claim], ledger: Ledger) -> tuple[list[Claim], list[str]]:
    """Keep claims whose every citation is ledgered; return (kept, unknown IDs)."""
    kept: list[Claim] = []
    rejected: list[str] = []
    for claim in claims:
        unknown = [r for r in claim.result_ids if r not in ledger.result_ids]
        unknown += [r for r in claim.rel_ids if r not in ledger.rel_ids]
        unknown += [n for n in claim.node_ids if n not in ledger.node_ids]
        if unknown:
            rejected.extend(unknown)
        elif claim.rel_ids or claim.node_ids:
            kept.append(claim)
    return kept, list(dict.fromkeys(rejected))


async def reverify(graph: GraphClient, claims: list[Claim]) -> tuple[list[Claim], list[str]]:
    """Keep claims whose cited relationships and nodes still exist; return (kept, missing IDs)."""
    rel_ids = sorted({r for c in claims for r in c.rel_ids})
    node_ids = sorted({n for c in claims for n in c.node_ids})
    present = await _existing(graph, rel_ids, node_ids)
    kept, missing = [], []
    for claim in claims:
        gone = [i for i in [*claim.rel_ids, *claim.node_ids] if i not in present]
        if gone:
            missing.extend(gone)
        else:
            kept.append(claim)
    return kept, list(dict.fromkeys(missing))


async def _existing(graph: GraphClient, rel_ids: list[str], node_ids: list[str]) -> set[str]:
    transfers = [r for r in rel_ids if r.startswith("tx_")]
    links = [r.split(":") for r in rel_ids if r.count(":") == 2]
    present: set[str] = set()
    if transfers:
        rows = await graph.read(
            "MATCH ()-[t:TRANSFER]->() WHERE t.id IN $ids RETURN t.id AS id", ids=transfers
        )
        present |= {r["id"] for r in rows}
    if links:
        rows = await graph.read(
            """
            UNWIND $links AS link
            MATCH (a {id: link[1]})-[r]->(b {id: link[2]})
            WHERE toLower(type(r)) = link[0]
            RETURN link[0] + ':' + link[1] + ':' + link[2] AS id
            """,
            links=links,
        )
        present |= {r["id"] for r in rows}
    if node_ids:
        rows = await graph.read(
            "MATCH (n) WHERE (n:Customer OR n:Account OR n:Device OR n:Alert) AND n.id IN $ids "
            "RETURN n.id AS id",
            ids=node_ids,
        )
        present |= {r["id"] for r in rows}
    return present
