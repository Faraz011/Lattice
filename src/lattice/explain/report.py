"""The circuit report: everything the narrator and the UI show about why a case was flagged."""

from typing import Literal

from pydantic import BaseModel

from lattice.explain.circuit import Circuit, find_circuit
from lattice.explain.counterfactual import CounterfactualResult, find_counterfactuals
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
    # Facts for every edge the report names: supporting evidence (which includes the circuit)
    # and the counterfactual removals.
    edges: list[EdgeDetail]


def build_report(graph: EvidenceGraph, scorer: Scorer) -> CircuitReport:
    circuit = find_circuit(graph, scorer)
    counterfactuals = find_counterfactuals(graph, circuit, scorer)
    named = set(circuit.supporting_edges) | {
        e for cf in counterfactuals.counterfactuals for e in cf.removed
    }
    edges = [
        EdgeDetail(id=t.id, kind="transfer", src=t.src, dst=t.dst, amount=t.amount,
                   ts=t.ts.isoformat())
        for t in graph.all_transfers if t.id in named
    ] + [
        EdgeDetail(id=link.id, kind="device_link", src=link.account_id, dst=link.device_id)
        for link in graph.all_links if link.id in named
    ]
    return CircuitReport(circuit=circuit, counterfactuals=counterfactuals,
                         reasons=scorer.score(graph).reasons, edges=edges)
