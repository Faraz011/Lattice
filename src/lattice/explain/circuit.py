"""The evidence circuit (R13, KTD8): ACDC-style pruning of cited evidence against the scorer.

1. Attribute every edge: its detector contribution plus the score lost when it alone is removed
   (the leave-one-out drop, which plays the role EAP plays for ACDC).
2. Prune greedily, lowest attribution first, keeping a removal only while the remaining edges
   still score at or above the threshold. What survives is the minimal sufficient circuit.
3. Comprehensiveness: the evidence minus the circuit must fall below the threshold. When it
   does not, a second independent body of evidence exists, and that is reported, not hidden.
"""

from typing import Literal

from pydantic import BaseModel

from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer


class Circuit(BaseModel):
    status: Literal["circuit", "below_threshold"]
    threshold: float
    full_score: float
    typology: str | None
    detectors: dict[str, float]
    circuit_edges: list[str]
    sufficiency_score: float
    remaining_score: float
    comprehensive: bool
    redundant: bool
    attribution: dict[str, float]


def attribute(graph: EvidenceGraph, scorer: Scorer) -> dict[str, float]:
    full = scorer.score(graph)
    attribution: dict[str, float] = {}
    for edge in graph.edge_ids():
        drop = full.score - scorer.score(graph.without({edge})).score
        attribution[edge] = round(full.edge_contributions.get(edge, 0.0) + max(0.0, drop), 6)
    return attribution


def find_circuit(graph: EvidenceGraph, scorer: Scorer) -> Circuit:
    full = scorer.score(graph)
    attribution = attribute(graph, scorer)
    if full.score < scorer.threshold:
        return Circuit(status="below_threshold", threshold=scorer.threshold,
                       full_score=full.score, typology=full.typology, detectors=full.detectors,
                       circuit_edges=[], sufficiency_score=0.0, remaining_score=full.score,
                       comprehensive=False, redundant=False, attribution=attribution)

    kept = set(graph.edge_ids())
    for edge in sorted(kept, key=lambda e: (attribution[e], e)):
        candidate = kept - {edge}
        if scorer.score(graph.only(candidate)).score >= scorer.threshold:
            kept = candidate

    order = {edge: i for i, edge in enumerate(graph.edge_ids())}
    circuit_edges = sorted(kept, key=lambda e: order[e])
    sufficiency = scorer.score(graph.only(kept)).score
    remaining = scorer.score(graph.without(kept)).score
    return Circuit(
        status="circuit",
        threshold=scorer.threshold,
        full_score=full.score,
        typology=full.typology,
        detectors=full.detectors,
        circuit_edges=circuit_edges,
        sufficiency_score=sufficiency,
        remaining_score=remaining,
        comprehensive=remaining < scorer.threshold,
        redundant=remaining >= scorer.threshold,
        attribution=attribution,
    )
