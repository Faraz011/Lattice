"""The transparent risk scorer (KTD7): weighted detectors, benign dampeners, attributable edges.

score = 1 - product(1 - weight * strength * dampening) over detectors, so independent signals
add up but no single weak one dominates. The typology is the strongest detector. Each edge's
contribution is the sum of its share of every detector that used it.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.dampeners import dampening
from lattice.scoring.detectors import DETECTORS, DetectorResult

DEFAULT_THRESHOLD = 0.6


@dataclass(frozen=True)
class ScoreResult:
    score: float
    typology: str | None
    detectors: dict[str, float] = field(default_factory=dict)
    edge_contributions: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)


class Scorer:
    def __init__(
        self, weights: dict[str, float] | None = None, threshold: float = DEFAULT_THRESHOLD
    ) -> None:
        self.weights = {name: 1.0 for name in DETECTORS} | (weights or {})
        self.threshold = threshold

    @classmethod
    def from_settings(cls, settings) -> "Scorer":
        return cls(settings.detector_weights, settings.risk_threshold)

    def score(self, g: EvidenceGraph) -> ScoreResult:
        effective: dict[str, float] = {}
        edges: dict[str, float] = defaultdict(float)
        reasons: dict[str, str] = {}
        for name, detect in DETECTORS.items():
            result: DetectorResult = detect(g)
            if result.strength <= 0:
                continue
            value = min(1.0, self.weights[name] * result.strength * dampening(g, result))
            if value <= 0:
                continue
            effective[name] = round(value, 6)
            reasons[name] = result.reason
            for edge, share in result.edges.items():
                edges[edge] += value * share

        score = 1 - math.prod(1 - v for v in effective.values())
        typology = max(sorted(effective), key=lambda n: effective[n]) if effective else None
        return ScoreResult(
            score=round(score, 6),
            typology=typology,
            detectors=effective,
            edge_contributions={e: round(v, 6) for e, v in sorted(edges.items())},
            reasons=reasons,
        )

    def flags(self, result: ScoreResult) -> bool:
        return result.score >= self.threshold
