"""Each planted typology has its defining shape; each decoy breaks a property its look-alike has."""

import random
from datetime import timedelta

import pytest

from lattice.datagen import decoys, typologies
from lattice.datagen.background import build_background
from lattice.datagen.builder import REPORTING_THRESHOLD, WINDOW_START, Pattern, WorldBuilder

START = WINDOW_START + timedelta(days=20)


@pytest.fixture
def builder() -> WorldBuilder:
    b = WorldBuilder(seed=11)
    build_background(b, random.Random(11), persons=20, businesses=4)
    return b


def run(builder: WorldBuilder, fn, seed: int = 5) -> Pattern:
    return fn(builder, random.Random(seed), START)


def transfers_of(builder: WorldBuilder, pattern: Pattern):
    return [builder.transfer_by_id(tid) for tid in pattern.transfer_ids]


def inflow_to(transfers, account_id):
    return [t for t in transfers if t.dst == account_id]


def outflow_from(transfers, account_id):
    return [t for t in transfers if t.src == account_id]


# --- planted typologies -------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_peeling_chain_forwards_most_of_each_inflow_quickly(builder, seed):
    pattern = run(builder, typologies.peeling_chain, seed)
    ts = transfers_of(builder, pattern)
    chain = pattern.path

    assert len(chain) >= 5
    for here, nxt in zip(chain, chain[1:], strict=False):
        received = sum(t.amount for t in inflow_to(ts, here))
        forwarded = [t for t in outflow_from(ts, here) if t.dst == nxt]
        peels = [t for t in outflow_from(ts, here) if t.dst != nxt]
        assert len(forwarded) == 1
        assert forwarded[0].amount >= 0.85 * received
        assert peels and all(p.amount <= 0.1 * received for p in peels)
        last_in = max(t.ts for t in inflow_to(ts, here))
        assert forwarded[0].ts - last_in <= timedelta(hours=48)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fan_in_structures_many_deposits_just_under_the_threshold(builder, seed):
    pattern = run(builder, typologies.fan_in_structuring, seed)
    ts = transfers_of(builder, pattern)
    deposits = inflow_to(ts, pattern.seed_account_id)

    assert len({t.src for t in deposits}) >= 10
    assert all(0.8 * REPORTING_THRESHOLD <= t.amount < REPORTING_THRESHOLD for t in deposits)
    assert max(t.ts for t in deposits) - min(t.ts for t in deposits) <= timedelta(days=7)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fan_out_splits_one_inflow_across_many_recipients_within_two_days(builder, seed):
    pattern = run(builder, typologies.fan_out, seed)
    ts = transfers_of(builder, pattern)
    hub = pattern.seed_account_id
    (inbound,) = inflow_to(ts, hub)
    outs = outflow_from(ts, hub)

    assert len({t.dst for t in outs}) >= 8
    assert all(t.ts - inbound.ts <= timedelta(hours=48) for t in outs)
    assert 0.9 * inbound.amount <= sum(t.amount for t in outs) <= inbound.amount


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_round_trip_returns_similar_amounts_to_the_origin_within_two_weeks(builder, seed):
    pattern = run(builder, typologies.round_trip, seed)
    ts = sorted(transfers_of(builder, pattern), key=lambda t: t.ts)

    assert ts[0].src == pattern.seed_account_id
    assert ts[-1].dst == pattern.seed_account_id
    for a, b in zip(ts, ts[1:], strict=False):
        assert a.dst == b.src
    assert ts[-1].ts - ts[0].ts <= timedelta(days=14)
    assert all(abs(t.amount - ts[0].amount) <= 0.2 * ts[0].amount for t in ts)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_rapid_layering_moves_funds_through_young_accounts_within_hours(builder, seed):
    pattern = run(builder, typologies.rapid_layering, seed)
    ts = transfers_of(builder, pattern)
    intermediaries = pattern.path[1:-1]

    assert len(intermediaries) >= 4
    for account_id in intermediaries:
        account = builder.account_by_id(account_id)
        first_seen = min(t.ts for t in inflow_to(ts, account_id))
        assert first_seen - account.created_at <= timedelta(days=14)
        (received,) = inflow_to(ts, account_id)
        (sent,) = outflow_from(ts, account_id)
        assert sent.amount >= 0.95 * received.amount
        assert sent.ts - received.ts <= timedelta(hours=24)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_shared_device_links_unrelated_customers_paying_one_destination(builder, seed):
    pattern = run(builder, typologies.shared_device, seed)
    ts = transfers_of(builder, pattern)
    (device_id,) = pattern.device_ids
    links = builder.batch.account_devices
    users = [link.account_id for link in links if link.device_id == device_id]
    owners = {builder.account_by_id(a).customer_id for a in users}

    assert len(users) >= 3
    assert len(owners) == len(users)
    destinations = {t.dst for t in ts if t.src in users}
    assert len(destinations) == 1


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_exit_path_ends_in_a_mixer_then_an_exchange(builder, seed):
    pattern = run(builder, typologies.exit_via_mixer, seed)
    kinds = [builder.account_by_id(a).kind for a in pattern.path]

    assert kinds[-2:] == ["mixer", "exchange"]
    assert pattern.path[0] == pattern.seed_account_id


# --- decoys break their look-alike's property --------------------------------------------


def test_payroll_decoy_is_a_regular_business_cadence_unlike_fan_out(builder):
    pattern = run(builder, decoys.payroll_fan_out)
    ts = transfers_of(builder, pattern)
    employer = builder.account_by_id(pattern.seed_account_id)

    assert employer.kind == "business"
    by_employee: dict[str, list] = {}
    for t in ts:
        by_employee.setdefault(t.dst, []).append(t)
    assert len(by_employee) >= 8
    for payments in by_employee.values():
        assert len(payments) >= 3
        assert len({p.amount for p in payments}) == 1
        assert len({p.ts.day for p in payments}) == 1


def test_merchant_decoy_receives_small_varied_payments_over_weeks_unlike_fan_in(builder):
    pattern = run(builder, decoys.merchant_fan_in)
    deposits = inflow_to(transfers_of(builder, pattern), pattern.seed_account_id)

    assert builder.account_by_id(pattern.seed_account_id).kind == "business"
    near_threshold = [t for t in deposits if t.amount >= 0.8 * REPORTING_THRESHOLD]
    assert not near_threshold
    assert max(t.ts for t in deposits) - min(t.ts for t in deposits) > timedelta(days=30)


def test_family_cycle_decoy_is_slow_with_unequal_amounts_between_old_accounts(builder):
    pattern = run(builder, decoys.family_cycle)
    ts = sorted(transfers_of(builder, pattern), key=lambda t: t.ts)

    assert ts[-1].dst == ts[0].src  # still a cycle, like round_trip
    assert ts[-1].ts - ts[0].ts > timedelta(days=14)
    assert any(abs(t.amount - ts[0].amount) > 0.2 * ts[0].amount for t in ts)
    for account_id in pattern.account_ids:
        assert START - builder.account_by_id(account_id).created_at > timedelta(days=365)


# --- shared behaviour ----------------------------------------------------------------------


@pytest.mark.parametrize("fn", typologies.ALL + decoys.ALL, ids=lambda f: f.__name__)
def test_same_rng_seed_gives_the_same_structure_with_fresh_ids(builder, fn):
    first = run(builder, fn, seed=9)
    second = run(builder, fn, seed=9)

    amounts = lambda p: sorted(t.amount for t in transfers_of(builder, p))  # noqa: E731
    assert amounts(first) == amounts(second)
    assert not set(first.transfer_ids) & set(second.transfer_ids)
    assert not set(first.account_ids) & set(second.account_ids)


@pytest.mark.parametrize("fn", typologies.ALL + decoys.ALL, ids=lambda f: f.__name__)
def test_seed_account_is_part_of_the_pattern(builder, fn):
    pattern = run(builder, fn)

    assert pattern.seed_account_id in pattern.account_ids
