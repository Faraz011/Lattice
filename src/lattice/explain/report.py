"""The circuit report: everything the narrator and the UI show about why a case was flagged."""

from typing import Literal

from pydantic import BaseModel

from lattice.explain.circuit import Circuit, find_circuit
from lattice.explain.counterfactual import CounterfactualResult, find_counterfactuals
from lattice.explain.llm_attribution import LLMAttribution
from lattice.explain.routes import (
    FreezeWhatIf,
    Route,
    SizeCurve,
    find_routes,
    freeze_whatifs,
    infer_roles,
    route_relation,
    size_curve,
)
from lattice.explain.sar import sar_draft
from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer


class EdgeDetail(BaseModel):
    id: str
    kind: Literal["transfer", "device_link"]
    src: str
    dst: str
    amount: float | None = None
    ts: str | None = None


class CircuitReport(BaseModel):
    circuit: Circuit
    counterfactuals: CounterfactualResult
    reasons: dict[str, str]
    # Facts for every edge the report names: supporting evidence (which includes the circuit),
    # the counterfactual removals, the routes and what freezing each account would stop.
    edges: list[EdgeDetail]
    # The scorer's proof first, then each independent backup route (routes.py).
    routes: list[Route] = []
    route_relation: str | None = None
    # Originator, mule or collector for each account on a route, from the routes' structure.
    roles: dict[str, str] = {}
    # What freezing each route account would do to this evidence.
    freeze_whatifs: list[FreezeWhatIf] = []
    size_curve: SizeCurve | None = None
    sar_draft: str | None = None
    # Which tool results the LLM's own judgement leaned on; tier 2-3 proposals only (U17).
    llm_attribution: LLMAttribution | None = None


def build_report(graph: EvidenceGraph, scorer: Scorer, subject: str | None = None) -> CircuitReport:
    """The circuit and everything that explains it. `subject` (the alerted account) adds a
    SAR draft for flagged cases."""
    circuit = find_circuit(graph, scorer)
    counterfactuals = find_counterfactuals(graph, circuit, scorer)
    routes = find_routes(graph, scorer, first=circuit) if circuit.status == "circuit" else []
    roles = infer_roles(graph, routes)
    whatifs = freeze_whatifs(graph, scorer, routes, roles)
    named = set(circuit.supporting_edges) | {
        e for cf in counterfactuals.counterfactuals for e in cf.removed
    } | {e for r in routes for e in r.edges} | {
        e for w in whatifs for e in [*w.removed_edges, *w.backup_edges]
    }
    edges = [
        EdgeDetail(id=t.id, kind="transfer", src=t.src, dst=t.dst, amount=t.amount,
                   ts=t.ts.isoformat() if t.ts else None)
        for t in graph.all_transfers if t.id in named
    ] + [
        EdgeDetail(id=link.id, kind="device_link", src=link.account_id, dst=link.device_id)
        for link in graph.all_links if link.id in named
    ]
    report = CircuitReport(
        circuit=circuit, counterfactuals=counterfactuals, reasons=scorer.score(graph).reasons,
        edges=edges, routes=routes, route_relation=route_relation(routes), roles=roles,
        freeze_whatifs=whatifs,
        size_curve=size_curve(graph, scorer, circuit) if circuit.status == "circuit" else None,
    )
    if subject is not None and circuit.status == "circuit":
        report.sar_draft = sar_draft(report, subject)
    return report
