"""Structural detectors on unpriced evidence graphs (Elliptic2-shaped): what fires them, what
does not, and the gate that keeps them away from priced evidence."""

from datetime import UTC, datetime
from typing import get_args

from lattice.agents.schemas import StructuralTypology
from lattice.explain.circuit import find_circuit
from lattice.graph.subgraph import AccountInfo, EvidenceGraph, Transfer
from lattice.scoring import structural
from lattice.scoring.scorer import Scorer

T0 = datetime(2026, 2, 1, 9, tzinfo=UTC)


def graph(*flows: tuple[str, str], priced: bool = False) -> EvidenceGraph:
    transfers = [
        Transfer(id=f"tx_{i}", src=src, dst=dst, amount=100.0 if priced else None,
                 ts=T0 if priced else None, channel="bitcoin")
        for i, (src, dst) in enumerate(flows)
    ]
    accounts = {a: AccountInfo(id=a, kind="cluster", created_at=None, customer_id=f"cust_{a}")
                for src, dst in flows for a in (src, dst)}
    return EvidenceGraph.build(transfers, accounts, [])


def ring(*accounts: str) -> list[tuple[str, str]]:
    return list(zip(accounts, [*accounts[1:], accounts[0]], strict=True))


def star(hub: str, n: int, outward: bool = True) -> list[tuple[str, str]]:
    return [(hub, f"{hub}_{i}") if outward else (f"{hub}_{i}", hub) for i in range(n)]


# --- cycle --------------------------------------------------------------------------------


def test_a_three_account_loop_fires_cycle_at_full_strength_with_its_edges():
    result = structural.structural_cycle(graph(*ring("a", "b", "c"), ("c", "x")))

    assert result.strength == 1.0
    assert set(result.edges) == {"tx_0", "tx_1", "tx_2"}
    assert result.anchor == "a"


def test_a_two_account_back_and_forth_is_not_a_cycle():
    assert structural.structural_cycle(graph(("a", "b"), ("b", "a"))).strength == 0


def test_the_longest_cycle_wins():
    result = structural.structural_cycle(graph(*ring("a", "b"), *ring("a", "c", "d", "e")))

    assert len(result.edges) == 4


def test_a_chain_without_a_way_back_is_not_a_cycle():
    assert structural.structural_cycle(graph(("a", "b"), ("b", "c"), ("c", "d"))).strength == 0


def test_breaking_the_loop_removes_the_cycle():
    g = graph(*ring("a", "b", "c"))

    assert structural.structural_cycle(g.without({"tx_1"})).strength == 0


def test_cycles_longer_than_the_search_limit_are_not_found():
    accounts = [f"n{i}" for i in range(structural.MAX_CYCLE + 1)]

    assert structural.structural_cycle(graph(*ring(*accounts))).strength == 0


# --- fan out / fan in ---------------------------------------------------------------------


def test_paying_many_distinct_counterparties_fires_fan_out():
    result = structural.structural_fan_out(graph(*star("hub", 12)))

    assert result.strength == 1.0
    assert result.anchor == "hub"
    assert len(result.edges) == 12


def test_repeat_payments_to_the_same_counterparties_do_not_count_twice():
    flows = star("hub", 6) * 3

    assert structural.structural_fan_out(graph(*flows)).strength == structural.structural_fan_out(
        graph(*star("hub", 6))).strength == 0.25


def test_four_or_fewer_counterparties_are_not_a_fan():
    assert structural.structural_fan_out(graph(*star("hub", 4))).strength == 0
    assert structural.structural_fan_in(graph(*star("hub", 4, outward=False))).strength == 0


def test_being_paid_by_many_distinct_counterparties_fires_fan_in_not_fan_out():
    g = graph(*star("hub", 10, outward=False))

    assert structural.structural_fan_in(g).strength == 0.75
    assert structural.structural_fan_in(g).anchor == "hub"
    assert structural.structural_fan_out(g).strength == 0


# --- dense group --------------------------------------------------------------------------


def test_four_accounts_all_trading_with_each_other_fire_dense_at_full_strength():
    accounts = ["a", "b", "c", "d"]
    flows = [(x, y) for i, x in enumerate(accounts) for y in accounts[i + 1:]]

    result = structural.structural_dense(graph(*flows, ("a", "outside")))

    assert result.strength == 1.0
    assert len(result.edges) == 6  # the link to the outside account is not part of the group


def test_a_four_account_ring_is_moderately_dense():
    result = structural.structural_dense(graph(*ring("a", "b", "c", "d")))

    assert 0.3 < result.strength < 0.6


def test_a_star_is_not_dense():
    assert structural.structural_dense(graph(*star("hub", 8))).strength == 0


def test_three_accounts_are_too_few_for_a_dense_group():
    assert structural.structural_dense(graph(*ring("a", "b", "c"), ("a", "c"))).strength == 0


# --- the gate and the scorer --------------------------------------------------------------


def test_structural_detectors_do_not_run_on_priced_evidence():
    result = Scorer().score(graph(*ring("a", "b", "c"), priced=True))

    assert not any(name.startswith("structural_") for name in result.detectors)


def test_structural_detectors_run_on_unpriced_evidence_and_a_loop_flags():
    scorer = Scorer()
    result = scorer.score(graph(*ring("a", "b", "c")))

    assert result.typology == "structural_cycle"
    assert scorer.flags(result)


def test_a_hub_paying_and_paid_by_many_never_flags():
    """An exchange: deposits in, withdrawals out, often to the same customers."""
    scorer = Scorer()

    assert not scorer.flags(scorer.score(graph(*star("hub", 30))))
    assert not scorer.flags(scorer.score(graph(*star("hub", 30), *star("hub", 30, False))))


def test_the_setting_can_force_structural_detectors_on_or_off():
    priced = graph(*ring("a", "b", "c"), priced=True)
    unpriced = graph(*ring("a", "b", "c"))

    assert "structural_cycle" in Scorer(structural="always").score(priced).detectors
    assert Scorer(structural="never").score(unpriced).score == 0


def test_the_gate_reads_the_whole_graph_so_ablation_cannot_switch_it():
    g = EvidenceGraph.build(
        [Transfer("tx_p", "x", "y", 5.0, T0, "wire"),
         *(Transfer(f"tx_{i}", s, d, None, None, "bitcoin")
           for i, (s, d) in enumerate(ring("a", "b", "c")))],
        {}, [])

    assert Scorer().score(g.without({"tx_p"})).score == 0


def test_an_unpriced_loop_gets_a_circuit_of_exactly_the_loop():
    g = graph(*ring("a", "b", "c"), ("c", "x"), ("y", "a"))

    circuit = find_circuit(g, Scorer())

    assert circuit.status == "circuit"
    assert set(circuit.circuit_edges) == {"tx_0", "tx_1", "tx_2"}
    assert circuit.comprehensive


def test_every_structural_detector_is_a_verdict_typology():
    assert set(structural.STRUCTURAL_DETECTORS) == set(get_args(StructuralTypology))
    assert set(structural.STRUCTURAL_WEIGHTS) == set(structural.STRUCTURAL_DETECTORS)


# --- tuning -------------------------------------------------------------------------------


def test_tuning_never_uses_evaluation_subgraphs_unless_told_to():
    from pathlib import Path

    from lattice.eval.tune_structural import labelled_cases

    sample = Path(__file__).resolve().parents[1] / "fixtures" / "elliptic2_sample"

    held_out, _ = labelled_cases(sample, 10, seed=7, eval_subgraphs=2, eval_seed=2,
                                 allow_overlap=False)
    everything, overlap = labelled_cases(sample, 10, seed=7, eval_subgraphs=2, eval_seed=2,
                                         allow_overlap=True)

    assert len(held_out) == 3 and len(everything) == 5
    assert overlap == 2


def test_the_search_finds_weights_that_separate_the_labels():
    from lattice.eval.tune_structural import Labelled, measure, search

    zero = dict.fromkeys(structural.STRUCTURAL_DETECTORS, 0.0)
    cases = [
        Labelled("s1", True, zero | {"structural_cycle": 1.0}),
        Labelled("s2", True, zero | {"structural_dense": 1.0}),
        Labelled("l1", False, zero | {"structural_fan_out": 1.0}),
        Labelled("l2", False, zero),
    ]

    best = search(cases)

    assert (best.recall, best.false_positive_rate) == (1.0, 0.0)
    assert measure(cases, best.weights) == best
