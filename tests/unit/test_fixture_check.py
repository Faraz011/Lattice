"""The fixture check's selection, quota refusal and resume, without a running stack."""

from collections import Counter

import pytest

from lattice.config import load_settings
from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.eval.fixture_check import (
    HELD_OUT_SEED,
    QuotaShortfall,
    State,
    check_quota,
    estimate_requests,
    run_alerts,
    select_alerts,
)

WORLD = generate_world(HELD_OUT_SEED, "fixture")


def test_the_held_out_world_is_not_the_world_the_scorer_was_tuned_on():
    tuned = generate_world(FIXTURE_SEED, "fixture")

    assert HELD_OUT_SEED != FIXTURE_SEED
    assert not {a.id for a in WORLD.batch.accounts} & {a.id for a in tuned.batch.accounts}


def test_twelve_stratified_alerts_one_per_typology_and_decoy_kind_plus_a_pair():
    alerts = select_alerts(WORLD)

    assert Counter(a.role for a in alerts) == {"planted": 7, "decoy": 3, "injected": 1, "twin": 1}
    assert len({a.case_kind for a in alerts if a.role == "planted"}) == 7
    assert len({a.case_kind for a in alerts if a.role == "decoy"}) == 3
    injected = next(a for a in alerts if a.role == "injected")
    twin = next(a for a in alerts if a.role == "twin")
    assert (injected.twin_alert_id, twin.twin_alert_id) == (twin.alert_id, injected.alert_id)
    assert select_alerts(WORLD) == alerts  # a fixed order, so a resumed run lines up


def test_expected_edges_include_shared_device_links():
    shared = next(a for a in select_alerts(WORLD) if a.case_kind == "shared_device")

    assert any(e.startswith("used_device:") for e in shared.expected_edges)


def test_with_less_quota_than_the_estimate_the_check_refuses_and_names_the_shortfall():
    estimate = estimate_requests(12, load_settings())

    with pytest.raises(QuotaShortfall, match=f"{estimate - 100} short"):
        check_quota(estimate, remaining=100)


def test_enough_quota_or_no_daily_cap_lets_the_check_start():
    estimate = estimate_requests(12, load_settings())

    check_quota(estimate, remaining=estimate)
    check_quota(estimate, remaining=None)


def test_the_estimate_scales_with_the_step_budget():
    settings = load_settings()
    bigger = settings.model_copy(update={"investigation_step_budget":
                                         settings.investigation_step_budget + 1})

    assert estimate_requests(12, bigger) - estimate_requests(12, settings) == 12 * 4


async def test_an_interrupted_run_resumes_at_the_next_alert_without_rerunning(tmp_path):
    alerts = select_alerts(WORLD)
    state = State(tmp_path / "state.json")
    calls: list[str] = []

    async def stops_after_five(alert):
        if len(calls) == 5:
            raise KeyboardInterrupt
        calls.append(alert.alert_id)
        return alert.model_copy(update={"status": "closed_no_action", "suspicious": False})

    with pytest.raises(KeyboardInterrupt):
        await run_alerts(alerts, stops_after_five, state)
    assert set(state.load()) == {a.alert_id for a in alerts[:5]}

    resumed: list[str] = []

    async def records(alert):
        resumed.append(alert.alert_id)
        return alert.model_copy(update={"status": "closed_no_action", "suspicious": False})

    outcomes = await run_alerts(alerts, records, state)

    assert resumed == [a.alert_id for a in alerts[5:]]
    assert [o.alert_id for o in outcomes] == [a.alert_id for a in alerts]
