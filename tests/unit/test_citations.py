from lattice.agents.schemas import Claim
from lattice.explain.citations import Ledger, check_against_ledger

LEDGER = Ledger(
    result_ids={"led_1", "led_2"},
    node_ids={"acct_a", "acct_b"},
    rel_ids={"tx_1", "tx_2", "tx_3"},
)


def claim(rel_ids=(), node_ids=(), result_ids=("led_1",)):
    return Claim(statement="s", rel_ids=list(rel_ids), node_ids=list(node_ids),
                 result_ids=list(result_ids))


def test_claims_citing_only_ledgered_ids_are_kept():
    good = claim(rel_ids=["tx_1", "tx_2"], node_ids=["acct_a"])

    kept, rejected = check_against_ledger([good], LEDGER)

    assert kept == [good]
    assert rejected == []


def test_a_claim_citing_a_fabricated_transfer_is_dropped_and_the_id_listed():
    forged = claim(rel_ids=["tx_1", "tx_forged"])

    kept, rejected = check_against_ledger([forged], LEDGER)

    assert kept == []
    assert rejected == ["tx_forged"]


def test_a_claim_citing_an_unknown_tool_result_is_dropped():
    unsourced = claim(rel_ids=["tx_1"], result_ids=["led_invented"])

    kept, rejected = check_against_ledger([unsourced], LEDGER)

    assert kept == []
    assert rejected == ["led_invented"]


def test_a_claim_with_no_evidence_at_all_is_dropped():
    bare = claim(rel_ids=[], node_ids=[])

    kept, _ = check_against_ledger([bare], LEDGER)

    assert kept == []


def test_rejected_ids_are_reported_once_each_across_claims():
    claims = [claim(rel_ids=["tx_x"]), claim(rel_ids=["tx_x", "tx_y"]), claim(rel_ids=["tx_3"])]

    kept, rejected = check_against_ledger(claims, LEDGER)

    assert [c.rel_ids for c in kept] == [["tx_3"]]
    assert rejected == ["tx_x", "tx_y"]
