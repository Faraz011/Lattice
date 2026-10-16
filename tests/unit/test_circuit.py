"""The evidence circuit (KTD8) on the fixture world and on hand-built graphs."""

import random

import pytest

from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.explain.circuit import find_circuit
from lattice.graph.subgraph import EvidenceGraph
from lattice.scoring.scorer import Scorer

WORLD = generate_world(seed=FIXTURE_SEED, size="fixture")
SCORER = Scorer()
PLANTED = [c for c in WORLD.manifest.cases if c.category == "planted"]
PLANTED_IDS = {t for c in WORLD.manifest.cases for t in c.transfer_ids}
BACKGROUND = sorted(t.id for t in WORLD.batch.transfers if t.id not in PLANTED_IDS)


def case_edges(case) -> list[str]:
    links = [f"used_device:{link.account_id}:{link.device_id}"
             for link in WORLD.batch.account_devices if link.device_id in case.device_ids]
    return [*case.transfer_ids, *links]


def with_noise(case, n=30, seed=1) -> EvidenceGraph:
    noise = random.Random(seed).sample(BACKGROUND, n)
    return EvidenceGraph.from_batch(WORLD.batch, case_edges(case) + noise)


def test_unrelated_cited_edges_are_pruned_and_the_chain_kept():
    case = next(c for c in PLANTED if c.kind == "peeling_chain")
    graph = with_noise(case)

    circuit = find_circuit(graph, SCORER)

    assert circuit.circuit_edges
    assert set(circuit.circuit_edges) <= set(case.transfer_ids)


@pytest.mark.parametrize("case", PLANTED, ids=lambda c: c.case_id)
def test_every_circuit_is_sufficient_on_its_own(case):
    graph = with_noise(case)

    circuit = find_circuit(graph, SCORER)

    assert circuit.sufficiency_score >= SCORER.threshold
    assert SCORER.score(graph.only(set(circuit.circuit_edges))).score >= SCORER.threshold


def test_a_single_chain_circuit_is_comprehensive():
    case = next(c for c in PLANTED if c.kind == "peeling_chain")
    graph = with_noise(case)

    circuit = find_circuit(graph, SCORER)

    assert circuit.comprehensive
    assert not circuit.redundant
    assert circuit.remaining_score < SCORER.threshold


def test_two_independent_chains_are_reported_as_redundant_evidence():
    first, second = [c for c in PLANTED if c.kind == "peeling_chain"][:2]
    graph = EvidenceGraph.from_batch(WORLD.batch, [*first.transfer_ids, *second.transfer_ids])

    circuit = find_circuit(graph, SCORER)

    assert circuit.redundant
    assert not circuit.comprehensive
    assert circuit.remaining_score >= SCORER.threshold


def test_a_graph_below_threshold_has_no_circuit():
    graph = EvidenceGraph.from_batch(WORLD.batch, BACKGROUND[:40])

    circuit = find_circuit(graph, SCORER)

    assert circuit.status == "below_threshold"
    assert circuit.circuit_edges == []


def test_circuits_are_deterministic():
    case = next(c for c in PLANTED if c.kind == "fan_in_structuring")

    assert find_circuit(with_noise(case), SCORER) == find_circuit(with_noise(case), SCORER)


@pytest.mark.parametrize("case", PLANTED, ids=lambda c: c.case_id)
def test_circuit_edges_fall_inside_the_planted_pattern(case):
    """The U15 precision target (70%) holds on every fixture case, with noise added."""
    circuit = find_circuit(with_noise(case, n=40, seed=7), SCORER)
    planted = set(case_edges(case))

    inside = sum(1 for e in circuit.circuit_edges if e in planted)
    assert inside / len(circuit.circuit_edges) >= 0.7


@pytest.mark.parametrize("case", PLANTED, ids=lambda c: c.case_id)
def test_supporting_evidence_recovers_the_planted_pattern(case):
    """Recall (60% target) is measured on every edge the detectors used, not the minimal proof."""
    circuit = find_circuit(with_noise(case, n=40, seed=7), SCORER)
    planted = set(case_edges(case))

    assert set(circuit.circuit_edges) <= set(circuit.supporting_edges)
    recall = len(set(circuit.supporting_edges) & planted) / len(planted)
    precision = len(set(circuit.supporting_edges) & planted) / len(circuit.supporting_edges)
    assert recall >= 0.6
    assert precision >= 0.7


def test_a_graph_below_threshold_has_no_supporting_evidence():
    circuit = find_circuit(EvidenceGraph.from_batch(WORLD.batch, BACKGROUND[:40]), SCORER)

    assert circuit.supporting_edges == []


def test_attribution_covers_every_edge_and_ranks_circuit_edges_higher():
    case = next(c for c in PLANTED if c.kind == "fan_out")
    graph = with_noise(case)

    circuit = find_circuit(graph, SCORER)

    assert set(circuit.attribution) == set(graph.edge_ids())
    weakest_circuit_edge = min(circuit.attribution[e] for e in circuit.circuit_edges)
    noise = set(graph.edge_ids()) - set(case.transfer_ids)
    assert all(circuit.attribution[e] <= weakest_circuit_edge for e in noise)
