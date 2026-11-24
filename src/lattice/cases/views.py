"""What the UI reads about a case: its record with parsed results, and its evidence graph.

The evidence graph is every edge the case's tool calls returned, taken from the ledger, so the
UI shows exactly what the agents saw. Each edge lists the ledger entries that returned it, which
is what an analyst sees when they click it, and lets a replay grow the graph call by call.
"""

import json
import logging
from typing import Any

from lattice.graph.client import GraphClient

log = logging.getLogger(__name__)

JSON_FIELDS = ("verdict", "circuit", "narrative", "findings")
MAX_EDGES = 600


def public(record: dict[str, Any]) -> dict[str, Any]:
    """A case or action record as JSON: internal keys dropped, timestamps as ISO strings."""
    out = {k: v for k, v in record.items() if k != "active_key"}
    for key, value in out.items():
        if hasattr(value, "to_native"):
            out[key] = value.to_native().isoformat()
    return out


def case_view(case: dict[str, Any]) -> dict[str, Any]:
    out = public(case)
    for key in JSON_FIELDS:
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    return out


async def case_evidence(graph: GraphClient, case_id: str, seed: str | None = None) -> dict:
    entries = await graph.read(
        """
        MATCH (l:LedgerEntry {case_id: $case_id})
        RETURN l.result_id AS result_id, l.tool AS tool, l.params AS params, l.ts AS ts,
               l.rel_ids AS rel_ids
        ORDER BY l.ts
        """,
        case_id=case_id,
    )
    sources: dict[str, list[str]] = {}
    ledger = {}
    for entry in entries:
        ledger[entry["result_id"]] = {
            "result_id": entry["result_id"],
            "tool": entry["tool"],
            "params": json.loads(entry["params"] or "{}"),
            "ts": entry["ts"].to_native().isoformat(),
        }
        for rel in entry["rel_ids"] or []:
            sources.setdefault(rel, []).append(entry["result_id"])

    # First seen first, so a capped graph keeps what the investigation found earliest.
    wanted = list(sources)[:MAX_EDGES]
    transfers = await graph.read(
        """
        MATCH (a:Account)-[t:TRANSFER]->(b:Account) WHERE t.id IN $ids
        RETURN t.id AS id, a.id AS src, b.id AS dst, t.amount AS amount, t.ts AS ts,
               t.channel AS channel
        """,
        ids=[e for e in wanted if e.startswith("tx_")],
    )
    pairs = [e.split(":")[1:] for e in wanted if e.startswith("used_device:")]
    links = await graph.read(
        """
        UNWIND $pairs AS pair
        MATCH (a:Account {id: pair[0]})-[:USED_DEVICE]->(d:Device {id: pair[1]})
        RETURN 'used_device:' + a.id + ':' + d.id AS id, a.id AS src, d.id AS dst
        """,
        pairs=[p for p in pairs if len(p) == 2],
    )
    edges = [
        {"id": t["id"], "kind": "transfer", "src": t["src"], "dst": t["dst"],
         "amount": t["amount"], "ts": t["ts"].to_native().isoformat() if t["ts"] else None,
         "channel": t["channel"],
         "sources": sources[t["id"]]}
        for t in transfers
    ] + [
        {"id": link["id"], "kind": "device_link", "src": link["src"], "dst": link["dst"],
         "sources": sources[link["id"]]}
        for link in links
    ]
    order = {e: i for i, e in enumerate(wanted)}
    edges.sort(key=lambda e: order[e["id"]])

    account_ids = sorted({e["src"] for e in edges} | {e["dst"] for e in edges
                                                       if e["kind"] == "transfer"}
                         | ({seed} if seed else set()))
    accounts = await graph.read(
        """
        MATCH (a:Account) WHERE a.id IN $ids
        OPTIONAL MATCH (c:Customer)-[:OWNS]->(a)
        RETURN a.id AS id, a.kind AS kind, c.id AS customer_id
        """,
        ids=account_ids,
    )
    nodes = [{"id": a["id"], "kind": "account", "account_kind": a["kind"],
              "customer_id": a["customer_id"]} for a in accounts]
    nodes += [{"id": d, "kind": "device"}
              for d in sorted({e["dst"] for e in edges if e["kind"] == "device_link"})]
    return {"nodes": nodes, "edges": edges, "ledger": ledger,
            "truncated": len(sources) > MAX_EDGES}


async def case_snapshot(graph: GraphClient, case_id: str) -> dict:
    """The case, its actions and its evidence graph: everything a replay shows besides events."""
    from lattice.cases.actions import ActionStore
    from lattice.cases.store import CaseStore

    case = await CaseStore(graph).get(case_id)
    return {
        "case": case_view(case),
        "actions": [public(a) for a in await ActionStore(graph).for_case(case_id)],
        "evidence": await case_evidence(graph, case_id, case.get("seed_account_id")),
    }


async def record_case(graph: GraphClient, events: Any, case_id: str) -> None:
    """Save (or refresh) the case's replay recording. Best effort: a failure is logged only."""
    from lattice.queue.replay import save_recording

    try:
        await save_recording(graph, events, case_id, await case_snapshot(graph, case_id))
    except Exception:
        log.exception("could not save the recording for %s", case_id)
