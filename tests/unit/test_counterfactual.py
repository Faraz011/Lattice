"""Counterfactuals: the smallest removals that flip the scorer's verdict on the evidence."""

from test_detectors import Builder, peeling

from lattice.explain.circuit import find_circuit
from lattice.explain.counterfactual import NO_COUNTERFACTUAL, find_counterfactuals
from lattice.scoring.scorer import Scorer

SCORER = Scorer()


def chain(hops: int):
    b = Builder()
    forwards = peeling(b, hops=hops)
    graph = b.graph()
    return graph, forwards, find_circuit(graph, SCORER)


def test_removing_one_middle_hop_flips_a_short_chain():
    graph, forwards, circuit = chain(hops=5)

    result = find_counterfactuals(graph, circuit, SCORER)

    singles = [cf.removed for cf in result.counterfactuals if len(cf.removed) == 1]
    assert [forwards[3]] in singles
    assert all(cf.score_after < SCORER.threshold for cf in result.counterfactuals)
    assert result.note is None


def test_when_no_single_edge_flips_the_verdict_a_pair_is_found():
    graph, forwards, circuit = chain(hops=7)

    result = find_counterfactuals(graph, circuit, SCORER)

    assert result.counterfactuals
    assert all(len(cf.removed) == 2 for cf in result.counterfactuals)
    for cf in result.counterfactuals:
        assert SCORER.score(graph.without(set(cf.removed))).score < SCORER.threshold


def test_redundant_evidence_has_no_counterfactual_within_the_bound():
    b = Builder()
    peeling(b, hops=6)
    # A second, independent chain through different accounts.
    from datetime import timedelta

    from test_detectors import T0, hours
    b.account("exchange2", kind="exchange")
    b.send("exchange2", "z0", 90_000, T0 + timedelta(days=1), "crypto")
    amount, t = 90_000.0, T0 + timedelta(days=1)
    for i in range(6):
        t += hours(6)
        b.send(f"z{i}", f"zcash{i}", amount * 0.05, t)
        amount *= 0.95
        b.send(f"z{i}", f"z{i + 1}", amount, t + hours(1))
    graph = b.graph()

    result = find_counterfactuals(graph, find_circuit(graph, SCORER), SCORER)

    assert result.counterfactuals == []
    assert result.note == NO_COUNTERFACTUAL


def test_counterfactuals_are_deterministic():
    graph, _, circuit = chain(hops=5)

    assert find_counterfactuals(graph, circuit, SCORER) == find_counterfactuals(graph, circuit,
                                                                                SCORER)
