import json
from collections import Counter
from pathlib import Path

import pytest

from lattice.datagen.generator import FIXTURE_SEED, generate_world
from lattice.datagen.injection import INJECTION_MEMOS
from lattice.graph.loader import _reject_duplicate_ids

FIXTURE_FILE = Path(__file__).parents[1] / "fixtures" / "small_world.json"


@pytest.fixture(scope="module")
def world():
    return generate_world(seed=FIXTURE_SEED, size="fixture")


def test_same_seed_produces_a_byte_identical_manifest():
    first = generate_world(seed=123, size="fixture").manifest.to_json()
    second = generate_world(seed=123, size="fixture").manifest.to_json()

    assert first == second


def test_different_seeds_produce_different_worlds():
    a = generate_world(seed=1, size="fixture").manifest.to_json()
    b = generate_world(seed=2, size="fixture").manifest.to_json()

    assert a != b


def test_every_manifest_id_exists_in_the_generated_graph(world):
    node_ids = set(world.batch.node_ids())
    transfer_ids = {t.id for t in world.batch.transfers}
    device_ids = {d.id for d in world.batch.devices}

    for case in world.manifest.cases:
        assert set(case.account_ids) <= node_ids, case.case_id
        assert set(case.transfer_ids) <= transfer_ids, case.case_id
        assert set(case.device_ids) <= device_ids, case.case_id
        assert case.seed_account_id in node_ids


def test_every_case_has_exactly_one_alert_seeded_from_its_own_accounts(world):
    alerts = {a.id: a for a in world.batch.alerts}
    alert_counts = Counter(case.alert_id for case in world.manifest.cases)

    assert len(alerts) == len(world.manifest.cases)
    for case in world.manifest.cases:
        assert alert_counts[case.alert_id] == 1
        assert alerts[case.alert_id].seed_account_id == case.seed_account_id
        assert case.seed_account_id in case.account_ids


def test_world_contains_every_planted_typology_and_decoy_kind(world):
    kinds = {(c.category, c.kind) for c in world.manifest.cases}

    for kind in ("peeling_chain", "fan_in_structuring", "fan_out", "round_trip",
                 "rapid_layering", "shared_device", "exit_via_mixer"):
        assert ("planted", kind) in kinds
    for kind in ("payroll_fan_out", "merchant_fan_in", "family_cycle"):
        assert ("decoy", kind) in kinds


def test_planted_cases_expect_suspicious_and_decoys_expect_benign(world):
    for case in world.manifest.cases:
        expected = "suspicious" if case.category == "planted" else "benign"
        assert case.expected_verdict == expected


def test_injection_memos_land_on_planted_and_benign_transfers_and_are_flagged(world):
    transfers = {t.id: t for t in world.batch.transfers}
    injected = [c for c in world.manifest.cases if c.injected_transfer_id]

    assert {c.category for c in injected} == {"planted", "decoy"}
    for case in injected:
        assert case.injected_transfer_id in case.transfer_ids
        assert transfers[case.injected_transfer_id].memo in INJECTION_MEMOS
    flagged = {c.injected_transfer_id for c in injected}
    unflagged_injections = [
        t.id for t in world.batch.transfers if t.memo in INJECTION_MEMOS and t.id not in flagged
    ]
    assert not unflagged_injections


def test_each_injection_case_has_a_memo_free_twin_with_the_same_structure(world):
    cases = {c.case_id: c for c in world.manifest.cases}
    transfers = {t.id: t for t in world.batch.transfers}

    for case in (c for c in cases.values() if c.injected_transfer_id):
        twin = cases[case.twin_case_id]
        assert twin.kind == case.kind and twin.category == case.category
        assert twin.twin_case_id == case.case_id
        assert twin.injected_transfer_id is None
        amounts = lambda c: sorted(transfers[t].amount for t in c.transfer_ids)  # noqa: E731
        assert amounts(twin) == amounts(case)
        assert all(transfers[t].memo not in INJECTION_MEMOS for t in twin.transfer_ids)


def test_generated_batch_has_no_duplicate_ids(world):
    _reject_duplicate_ids(world.batch)


def test_alert_reasons_do_not_reveal_the_answer(world):
    for alert in world.batch.alerts:
        lowered = alert.reason.lower()
        assert "decoy" not in lowered and "benign" not in lowered and "planted" not in lowered


def test_committed_fixture_matches_the_generator():
    committed = json.loads(FIXTURE_FILE.read_text())
    regenerated = json.loads(generate_world(seed=FIXTURE_SEED, size="fixture").to_json())

    hint = "regenerate with: python -m lattice.datagen.cli --write-fixture"
    assert committed == regenerated, hint
