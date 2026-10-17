"""The evaluation harness: subset selection, the report, and running with a concurrency cap."""

import asyncio
from collections import Counter

import pytest

from lattice.config import load_settings
from lattice.datagen.generator import DEMO_SEED, generate_world
from lattice.eval.fixture_check import State
from lattice.eval.harness import (
    all_alerts,
    estimate,
    plan_run,
    requests_per_alert,
    run_all,
    state_key,
    stratified_subset,
)
from lattice.eval.report import Pricing, render_report

WORLD = generate_world(DEMO_SEED, "demo")
ALERTS = all_alerts(WORLD)
SETTINGS = load_settings()
BOTH = ("single", "orchestrated")


def strata(alerts):
    """Units per stratum; an injection pair is one unit of two alerts."""
    return Counter("injection pair" if a.role == "injected" else f"{a.role} {a.case_kind}"
                   for a in alerts if a.role != "twin")


def test_every_demo_alert_is_included_with_its_role():
    assert len(ALERTS) == len(WORLD.batch.alerts)
    roles = Counter(a.role for a in ALERTS)
    assert roles["planted"] and roles["decoy"]
    assert roles["injected"] == roles["twin"]


def test_the_same_seed_picks_the_same_subset():
    first = stratified_subset(ALERTS, 20, seed=5)
    second = stratified_subset(ALERTS, 20, seed=5)

    assert [a.alert_id for a in first] == [a.alert_id for a in second]
    assert [a.alert_id for a in stratified_subset(ALERTS, 20, seed=6)] != \
        [a.alert_id for a in first]


def test_the_subset_covers_every_kind_before_repeating_one():
    kinds = {f"{a.role} {a.case_kind}" for a in ALERTS if a.role in ("planted", "decoy")}

    subset = stratified_subset(ALERTS, 20, seed=5)

    assert len(subset) <= 20
    assert kinds <= {f"{a.role} {a.case_kind}" for a in subset}
    assert max(strata(subset).values()) - min(strata(subset).values()) <= 2


def test_injection_pairs_stay_together():
    subset = stratified_subset(ALERTS, 30, seed=5)
    ids = {a.alert_id for a in subset}

    for alert in subset:
        if alert.role in ("injected", "twin"):
            assert alert.twin_alert_id in ids


def test_with_enough_quota_every_alert_runs():
    chosen, subset = plan_run(ALERTS, BOTH, SETTINGS, remaining=None, seed=5)
    assert subset is None and chosen == ALERTS

    chosen, subset = plan_run(ALERTS, BOTH, SETTINGS,
                              remaining=estimate(len(ALERTS), BOTH, SETTINGS), seed=5)
    assert subset is None and len(chosen) == len(ALERTS)


def test_on_a_short_quota_the_subset_fits_and_is_named():
    remaining = 1500

    chosen, subset = plan_run(ALERTS, BOTH, SETTINGS, remaining=remaining, seed=5)

    assert subset is not None
    assert estimate(len(chosen), BOTH, SETTINGS) <= remaining
    assert subset.alert_ids == [a.alert_id for a in chosen]
    report = render_report([a.model_copy(update={"mode": m}) for a in chosen for m in BOTH],
                           model="scripted", world="demo", modes=BOTH, subset=subset,
                           pricing=Pricing())
    assert f"Subset: {len(chosen)} of {len(ALERTS)} alerts" in report
    assert "seed 5" in report
    assert all(alert_id in report for alert_id in subset.alert_ids)


def test_a_single_agent_case_costs_less_than_an_orchestrated_one():
    assert requests_per_alert("single", SETTINGS) < requests_per_alert("orchestrated", SETTINGS)


def outcome(alert, mode, flagged, **extra):
    return alert.model_copy(update={
        "mode": mode, "suspicious": flagged, "status": "awaiting_approval" if flagged
        else "closed_no_action", "seconds": 10.0, "tool_calls": {"graph_match_pattern": 2},
        "usage": {"investigator": {"requests": 4, "cached": 1, "input_tokens": 1000,
                                   "output_tokens": 200}}, **extra})


def test_the_report_compares_modes_only_when_both_ran():
    planted = next(a for a in ALERTS if a.role == "planted")
    decoy = next(a for a in ALERTS if a.role == "decoy")
    both = [outcome(planted, "single", False), outcome(planted, "orchestrated", True),
            outcome(decoy, "single", False), outcome(decoy, "orchestrated", False)]

    compared = render_report(both, model="m", world="demo", modes=BOTH, subset=None,
                             pricing=Pricing(1.0, 2.0))
    single_only = render_report(both[::2], model="m", world="demo", modes=("single",),
                                subset=None, pricing=Pricing())

    assert "## Mode comparison" in compared
    assert f"{planted.alert_id} ({planted.case_kind}, planted): single not flagged " \
           "(closed_no_action), orchestrated flagged (awaiting_approval)" in compared
    assert "ended 1 differently" in compared
    assert "| Decision accuracy | 50% | 100% |" in compared
    assert "$0.0014" in compared  # (1000 * 1 + 200 * 2) / 1e6
    assert "## Mode comparison" not in single_only
    assert "not priced" in single_only
    assert "Every alert in the world was run." in compared


class Stop(Exception):
    pass


async def test_runs_each_mode_once_with_at_most_n_alerts_in_flight_and_resumes(tmp_path):
    alerts = ALERTS[:6]
    state = State(tmp_path / "s.json", key=state_key)
    in_flight = peak = 0
    order: list[tuple[str, str]] = []

    async def investigate(alert, mode):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        order.append((alert.alert_id, mode))
        if len(order) == 7:
            raise Stop
        return outcome(alert, mode, False)

    with pytest.raises(ExceptionGroup) as stopped:
        await run_all(alerts, BOTH, investigate, state, concurrency=2)
    assert stopped.group_contains(Stop)
    assert peak <= 2
    saved = len(state.load())
    assert 6 <= saved < 12

    order.clear()
    outcomes = await run_all(alerts, BOTH, investigate, state, concurrency=2)

    assert len(order) == 12 - saved  # only what was not finished
    assert [(o.alert_id, o.mode) for o in outcomes] == [(a.alert_id, m) for a in alerts
                                                        for m in BOTH]
    for alert in alerts:  # an alert's modes run in order, never at once
        modes = [m for a, m in order if a == alert.alert_id]
        assert modes in ([], ["orchestrated"], ["single", "orchestrated"])


def test_the_daily_case_cap_limits_the_subset_and_is_named():
    chosen, subset = plan_run(ALERTS, BOTH, SETTINGS, remaining=None, seed=5, case_room=20)

    assert subset is not None
    assert len(chosen) * len(BOTH) <= 20
    assert "LATTICE_MAX_CASES_PER_DAY" in subset.reason


def test_the_tighter_of_the_two_limits_wins():
    _, by_cases = plan_run(ALERTS, BOTH, SETTINGS, remaining=1500, seed=5, case_room=10)
    _, by_requests = plan_run(ALERTS, BOTH, SETTINGS, remaining=200, seed=5, case_room=100)

    assert len(by_cases.alert_ids) <= 5 and "cases" in by_cases.reason
    assert "model requests" in by_requests.reason
