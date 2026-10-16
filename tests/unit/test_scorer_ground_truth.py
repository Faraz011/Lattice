"""The scorer against the fixture world's answer key (KTD7). Tuned on this world only."""

import random
import time

import pytest

from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer

WORLD = generate_world(seed=FIXTURE_SEED, size="fixture")
SCORER = Scorer()


def evidence(case) -> EvidenceGraph:
    links = [f"used_device:{link.account_id}:{link.device_id}"
             for link in WORLD.batch.account_devices if link.device_id in case.device_ids]
    return EvidenceGraph.from_batch(WORLD.batch, [*case.transfer_ids, *links])


PLANTED = [c for c in WORLD.manifest.cases if c.category == "planted"]
DECOYS = [c for c in WORLD.manifest.cases if c.category == "decoy"]


@pytest.mark.parametrize("case", PLANTED, ids=lambda c: c.case_id)
def test_each_planted_case_scores_above_threshold_with_its_own_label(case):
    result = SCORER.score(evidence(case))

    assert result.score >= SCORER.threshold, result.detectors
    assert result.typology == case.kind


@pytest.mark.parametrize("case", DECOYS, ids=lambda c: c.case_id)
def test_each_decoy_scores_below_threshold(case):
    result = SCORER.score(evidence(case))

    assert result.score < SCORER.threshold, result.detectors


def test_random_background_activity_stays_below_threshold():
    planted = {t for c in WORLD.manifest.cases for t in c.transfer_ids}
    background = [t.id for t in WORLD.batch.transfers if t.id not in planted]
    rng = random.Random(3)

    for _ in range(20):
        sample = rng.sample(background, 200)
        assert SCORER.score(EvidenceGraph.from_batch(WORLD.batch, sample)).score < SCORER.threshold


def test_configured_weights_change_the_decision():
    case = next(c for c in PLANTED if c.kind == "peeling_chain")

    muted = Scorer(weights={"peeling_chain": 0.0}).score(evidence(case))
    halved = Scorer(weights={"peeling_chain": 0.5}).score(evidence(case))

    assert muted.score < SCORER.threshold
    assert halved.score == 0.5


def test_an_empty_graph_scores_zero_with_no_typology():
    result = SCORER.score(EvidenceGraph.from_batch(WORLD.batch, []))

    assert result.score == 0
    assert result.typology is None
    assert result.edge_contributions == {}


def test_scoring_is_deterministic():
    case = PLANTED[0]

    assert SCORER.score(evidence(case)) == SCORER.score(evidence(case))


def test_edge_contributions_cover_only_edges_in_the_graph():
    case = next(c for c in PLANTED if c.kind == "peeling_chain")
    graph = evidence(case)

    result = SCORER.score(graph)

    assert set(result.edge_contributions) <= set(graph.edge_ids())
    assert all(v >= 0 for v in result.edge_contributions.values())
    assert sum(result.edge_contributions.values()) > 0


def test_rescoring_a_200_edge_graph_is_fast_enough_for_circuit_search():
    case = PLANTED[0]
    planted_ids = list(case.transfer_ids)
    others = [t.id for t in WORLD.batch.transfers if t.id not in set(planted_ids)]
    graph = EvidenceGraph.from_batch(WORLD.batch, planted_ids + others[: 200 - len(planted_ids)])
    edges = graph.edge_ids()
    assert len(edges) == 200

    started = time.perf_counter()
    for i in range(500):
        SCORER.score(graph.without({edges[i % len(edges)]}))
    per_rescore = (time.perf_counter() - started) / 500

    # 10,000 rescorings (a generous circuit search) must fit in about a minute.
    assert per_rescore < 0.006, f"{per_rescore * 1000:.2f} ms per rescore"
