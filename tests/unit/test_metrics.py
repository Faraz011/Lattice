"""Success Criteria metrics on hand-built outcomes, checked against hand-computed numbers."""

from lattice.eval.metrics import AlertOutcome, compute, render

PATTERN = ["tx_1", "tx_2", "tx_3", "tx_4", "tx_5"]
STATUS = {True: "awaiting_approval", False: "closed_no_action", None: None}


def planted(alert, *, suspicious=True, circuit=(), supporting=(), **kw):
    return AlertOutcome(alert_id=alert, case_kind="peeling_chain", role="planted",
                        expected_suspicious=True, expected_edges=PATTERN, suspicious=suspicious,
                        status=STATUS[suspicious], circuit_edges=list(circuit),
                        supporting_edges=list(supporting), **kw)


def decoy(alert, *, suspicious=False, **kw):
    return AlertOutcome(alert_id=alert, case_kind="payroll_fan_out", role="decoy",
                        expected_suspicious=False, expected_edges=["tx_9"], suspicious=suspicious,
                        status="awaiting_approval" if suspicious else "closed_no_action", **kw)


def target(metrics, prefix):
    return next(t for t in metrics.targets if t.name.startswith(prefix))


def test_rates_precision_and_recall_match_hand_computed_values():
    outcomes = [
        # circuit 3 edges, 2 inside -> precision 2/3; supporting finds 4 of 5 -> recall 0.8
        planted("a1", circuit=["tx_1", "tx_2", "tx_x"], supporting=PATTERN[:4]),
        # circuit 2 inside -> precision 1.0; supporting finds 2 of 5 -> recall 0.4
        planted("a2", circuit=["tx_1", "tx_2"], supporting=["tx_1", "tx_2"]),
        planted("a3", suspicious=False),
        planted("a4", circuit=["tx_5"], supporting=["tx_5", "tx_4", "tx_3"]),  # 1.0, 0.6
        decoy("d1"), decoy("d2", suspicious=True), decoy("d3"), decoy("d4"), decoy("d5"),
    ]

    metrics = compute(outcomes)

    assert (metrics.planted, metrics.planted_flagged) == (4, 3)
    assert target(metrics, "Planted").value == 0.75 and not target(metrics, "Planted").met
    assert target(metrics, "Decoys").value == 0.2 and target(metrics, "Decoys").met
    assert abs(metrics.precision - (2 / 3 + 1 + 1) / 3) < 1e-9
    assert abs(metrics.recall - (0.8 + 0.4 + 0.6) / 3) < 1e-9
    assert target(metrics, "Circuit precision").met
    assert target(metrics, "Supporting-evidence recall").met


def test_a_case_without_a_verdict_is_a_miss_not_an_error():
    outcomes = [planted("a1", circuit=["tx_1"], supporting=PATTERN),
                planted("a2", suspicious=None, error="timed out after 600s")]

    metrics = compute(outcomes)

    assert metrics.planted_flagged == 1
    assert metrics.without_verdict == 1
    assert target(metrics, "Planted").value == 0.5
    assert "timed out after 600s" in render(metrics, outcomes, "t", [])


def test_any_unledgered_citation_misses_the_zero_target():
    metrics = compute([planted("a1", circuit=["tx_1"], supporting=PATTERN,
                               unledgered_ids=["tx_fake"])])

    assert metrics.unledgered == 1
    assert not target(metrics, "Unledgered").met


def test_an_injection_pair_with_different_verdicts_fails_the_twin_check():
    injected = AlertOutcome(alert_id="inj", case_kind="round_trip", role="injected",
                            expected_suspicious=True, expected_edges=PATTERN, twin_alert_id="twn",
                            suspicious=False, status="closed_no_action")
    twin = AlertOutcome(alert_id="twn", case_kind="round_trip", role="twin",
                        expected_suspicious=True, expected_edges=PATTERN, twin_alert_id="inj",
                        suspicious=True, status="awaiting_approval")

    metrics = compute([injected, twin])

    assert [t.same_verdict for t in metrics.twins] == [False]
    assert not target(metrics, "Injection").met
    assert "DIFFERENT verdicts" in render(metrics, [injected, twin], "t", [])


def test_a_matching_injection_pair_passes():
    common = dict(case_kind="round_trip", expected_suspicious=True, expected_edges=PATTERN,
                  suspicious=True, status="awaiting_approval")
    metrics = compute([
        AlertOutcome(alert_id="inj", role="injected", twin_alert_id="twn", **common),
        AlertOutcome(alert_id="twn", role="twin", twin_alert_id="inj", **common),
    ])

    assert target(metrics, "Injection").met


def test_sufficiency_and_comprehensiveness_are_counted_over_circuits():
    metrics = compute([
        planted("a1", circuit=["tx_1"], supporting=PATTERN, sufficient=True, comprehensive=True),
        planted("a2", circuit=["tx_2"], supporting=PATTERN, sufficient=True, comprehensive=False),
        planted("a3", suspicious=False),
    ])

    assert (metrics.circuits, metrics.sufficient, metrics.comprehensive) == (2, 2, 1)
