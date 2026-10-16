"""Counterfactuals (R13): the smallest removals from the evidence that flip the scorer's verdict.

The search is bounded. It tries single circuit edges first, then pairs among the most-attributed
circuit edges. A flip is judged on the whole evidence graph, so when independent evidence
remains (see `Circuit.redundant`), no small removal flips the verdict, and the report says so.
"""

from itertools import combinations

from pydantic import BaseModel

from lattice.explain.circuit import Circuit
from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer

NO_COUNTERFACTUAL = "no counterfactual within bound"
PAIR_CANDIDATES = 10
MAX_REPORTED = 5


class Counterfactual(BaseModel):
    removed: list[str]
    score_after: float
    typology_after: str | None


class CounterfactualResult(BaseModel):
    counterfactuals: list[Counterfactual]
    note: str | None = None


def find_counterfactuals(
    graph: EvidenceGraph, circuit: Circuit, scorer: Scorer, pair_candidates: int = PAIR_CANDIDATES
) -> CounterfactualResult:
    if circuit.status != "circuit":
        return CounterfactualResult(counterfactuals=[], note="verdict is below the threshold")

    ranked = sorted(circuit.circuit_edges, key=lambda e: (-circuit.attribution[e], e))

    def flips(removed: tuple[str, ...]) -> Counterfactual | None:
        result = scorer.score(graph.without(set(removed)))
        if result.score < scorer.threshold:
            return Counterfactual(removed=list(removed), score_after=result.score,
                                  typology_after=result.typology)
        return None

    found = [cf for edge in ranked if (cf := flips((edge,)))]
    if not found:
        found = [cf for pair in combinations(ranked[:pair_candidates], 2) if (cf := flips(pair))]
    found.sort(key=lambda cf: (cf.score_after, cf.removed))
    if not found:
        return CounterfactualResult(counterfactuals=[], note=NO_COUNTERFACTUAL)
    return CounterfactualResult(counterfactuals=found[:MAX_REPORTED])
