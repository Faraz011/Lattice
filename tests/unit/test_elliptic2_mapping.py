"""Elliptic2 slice mapping, on a small sample in the dataset's own file layout."""

from pathlib import Path

from lattice.graph.subgraph import EvidenceGraph
from lattice.ingest.elliptic2 import (
    account_id,
    alert_id,
    build_slice,
    choose_subgraphs,
    transfer_id,
)
from lattice.scoring import detectors
from lattice.scoring.scorer import Scorer

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "elliptic2_sample"
SLICE = build_slice(SAMPLE, subgraphs=10, neighbors=3, seed=2)


def test_the_sample_maps_to_the_expected_node_and_relationship_counts():
    batch = SLICE.batch

    assert len(batch.accounts) == 17  # 11 members + 6 one-hop neighbours
    assert len(batch.customers) == 17
    assert len(batch.transfers) == 14  # 7 internal flows + 7 background flows
    assert len(batch.alerts) == 5
    assert {a.kind for a in batch.accounts} == {"cluster"}


def test_flows_carry_no_amount_or_time():
    assert all(t.amount is None and t.ts is None for t in SLICE.batch.transfers)
    assert all(a.created_at is None for a in SLICE.batch.accounts)


def test_the_neighbourhood_is_capped_per_cluster_and_excludes_unrelated_flows():
    ids = {t.id for t in SLICE.batch.transfers}

    background = [t for t in SLICE.batch.transfers
                  if t.src == account_id("4") and t.dst != account_id("5")]
    assert len(background) == 3  # 4 had five background flows; the cap is three
    assert transfer_id("500", "501") not in ids
    assert transfer_id("9", "6") in ids  # a flow between two sampled subgraphs


def test_repeated_flows_become_one_transfer():
    ids = [t.id for t in SLICE.batch.transfers]

    assert len(ids) == len(set(ids))
    cc3 = next(c for c in SLICE.manifest.cases if c.case_id == "elliptic2-cc3")
    assert cc3.transfer_ids == [transfer_id("6", "7"), transfer_id("6", "8")]


def test_a_tagged_slice_shares_no_id_with_the_untagged_one():
    tagged = build_slice(SAMPLE, subgraphs=10, neighbors=3, seed=2, tag="test_")

    def ids(batch):
        return set(batch.node_ids()) | {t.id for t in batch.transfers}

    assert not ids(tagged.batch) & ids(SLICE.batch)
    assert len(ids(tagged.batch)) == len(ids(SLICE.batch))
    assert account_id("1", "test_") == "acct_elltest_1"
    seeds = {c.seed_account_id for c in tagged.manifest.cases}
    assert seeds <= {a.id for a in tagged.batch.accounts}


def test_labelled_subgraph_members_appear_in_the_manifest():
    cases = {c.case_id: c for c in SLICE.manifest.cases}

    cc1 = cases["elliptic2-cc1"]
    assert cc1.category == "planted" and cc1.expected_verdict == "suspicious"
    assert cc1.account_ids == [account_id(c) for c in ("1", "2", "3")]
    assert set(cc1.transfer_ids) == {transfer_id("1", "2"), transfer_id("2", "3"),
                                     transfer_id("3", "1")}
    assert cases["elliptic2-cc2"].category == "decoy"
    assert cases["elliptic2-cc2"].expected_verdict == "benign"
    assert SLICE.manifest.world == "elliptic2"


def test_each_alert_starts_at_the_best_connected_member_and_hides_the_label():
    alerts = {a.id: a for a in SLICE.batch.alerts}

    assert alerts[alert_id("cc3")].seed_account_id == account_id("6")
    assert alerts[alert_id("cc4")].seed_account_id == account_id("9")
    for alert in alerts.values():
        assert "suspicious" not in alert.reason and "licit" not in alert.reason


def test_the_sample_is_balanced_and_the_same_seed_picks_the_same_subgraphs():
    labels = {f"s{i}": "suspicious" for i in range(10)} | {f"l{i}": "licit" for i in range(90)}

    chosen = choose_subgraphs(labels, 20, seed=4)

    assert sum(c.startswith("s") for c in chosen) == 10
    assert chosen == choose_subgraphs(labels, 20, seed=4)
    assert chosen != choose_subgraphs(labels, 20, seed=5)


def test_missing_amounts_and_times_give_zero_detector_contribution_not_errors():
    graph = EvidenceGraph.from_batch(SLICE.batch, [t.id for t in SLICE.batch.transfers])

    for detector in detectors.DETECTORS.values():
        result = detector(graph)
        assert result.strength == 0.0

    score = Scorer().score(graph)
    assert score.score == 0.0
    assert score.typology is None


def test_the_harness_can_run_a_slice_against_its_labels():
    from lattice.eval.harness import alerts_from_manifest

    alerts = {a.alert_id: a for a in alerts_from_manifest(SLICE.manifest)}

    cc1 = alerts[alert_id("cc1")]
    assert cc1.role == "planted" and cc1.expected_suspicious
    assert set(cc1.expected_edges) == {transfer_id("1", "2"), transfer_id("2", "3"),
                                       transfer_id("3", "1")}
    assert alerts[alert_id("cc2")].role == "decoy"
