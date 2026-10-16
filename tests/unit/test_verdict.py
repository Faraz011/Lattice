"""How findings and the scorer combine into a case outcome (R15, KTD11)."""

from lattice.agents.schemas import Finding
from lattice.explain.verdict import decide
from lattice.scoring.scorer import ScoreResult

THRESHOLD = 0.6


def finding(hypothesis, verdict, confidence=0.8, status="complete"):
    if status != "complete":
        return Finding.partial(hypothesis, "rate budget exhausted", status)
    return Finding(hypothesis=hypothesis, verdict=verdict, confidence=confidence,
                   summary="s", claims=[])


def score(value, typology=None):
    return ScoreResult(score=value, typology=typology)


def test_agreement_on_laundering_awaits_approval_with_the_scorer_typology():
    outcome = decide("case_1", [finding("fan_out", "supports")], score(0.95, "fan_out"),
                     THRESHOLD, [], [])

    assert outcome.status == "awaiting_approval"
    assert outcome.verdict.suspicious
    assert outcome.verdict.typology == "fan_out"
    assert outcome.verdict.risk == "high"


def test_agreement_that_nothing_is_wrong_closes_the_case():
    outcome = decide("case_1", [finding("fan_out", "refutes")], score(0.1), THRESHOLD, [], [])

    assert outcome.status == "closed_no_action"
    assert not outcome.verdict.suspicious


def test_investigators_supporting_a_hypothesis_the_scorer_rejects_go_to_review():
    outcome = decide("case_1", [finding("fan_out", "supports")], score(0.0), THRESHOLD, [], [])

    assert outcome.status == "needs_review"
    assert "disagree" in outcome.verdict.review_reason


def test_the_scorer_flagging_what_investigators_refuted_goes_to_review():
    outcome = decide("case_1", [finding("peeling_chain", "refutes")],
                     score(0.9, "peeling_chain"), THRESHOLD, [], [])

    assert outcome.status == "needs_review"


def test_one_supported_hypothesis_among_refuted_alternatives_is_suspicious():
    findings = [finding("fan_out", "refutes"), finding("peeling_chain", "supports", 0.7),
                finding("round_trip", "refutes")]

    outcome = decide("case_1", findings, score(1.0, "peeling_chain"), THRESHOLD, [], [])

    assert outcome.status == "awaiting_approval"


def test_the_highest_confidence_supported_typology_labels_the_investigators_view():
    findings = [finding("fan_out", "supports", 0.6), finding("peeling_chain", "supports", 0.9)]

    outcome = decide("case_1", findings, score(0.0), THRESHOLD, [], [])

    assert outcome.verdict.investigator_typology == "peeling_chain"


def test_partial_findings_never_count_as_support_and_are_noted():
    findings = [finding("fan_out", "supports"), finding("peeling_chain", "x", status="partial")]

    outcome = decide("case_1", findings, score(0.9, "fan_out"), THRESHOLD, [], [])

    assert outcome.status == "awaiting_approval"
    assert any("partial" in note for note in outcome.verdict.notes)


def test_with_no_complete_finding_the_case_goes_to_review():
    findings = [finding("fan_out", "x", status="partial"), finding("open", "x", status="failed")]

    outcome = decide("case_1", findings, score(0.9, "fan_out"), THRESHOLD, [], [])

    assert outcome.status == "needs_review"
    assert "no investigator finished" in outcome.verdict.review_reason


def test_rejected_and_unverified_ids_are_carried_into_the_verdict():
    outcome = decide("case_1", [finding("fan_out", "refutes")], score(0.0), THRESHOLD,
                     ["tx_forged"], ["tx_deleted"])

    assert outcome.verdict.rejected_citations == ["tx_forged"]
    assert outcome.verdict.unverified_ids == ["tx_deleted"]


def test_risk_bands_follow_the_score():
    def risk(value):
        return decide("c", [finding("fan_out", "supports")], score(value, "fan_out"),
                      THRESHOLD, [], []).verdict.risk

    assert risk(0.95) == "high"
    assert risk(0.7) == "medium"
