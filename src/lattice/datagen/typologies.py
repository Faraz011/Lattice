"""Planted laundering typologies (R1). Each returns the exact accounts and transfers it created.

Funding and exit counterparties (exchanges, mixers, employers) come from the background and
are not pattern members; everything the pattern created is.
"""

import random
from datetime import datetime

from lattice.datagen.builder import REPORTING_THRESHOLD, Pattern, WorldBuilder, days, hours


def peeling_chain(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """A large deposit walks down a chain; each hop skims a small slice to a cash-out account."""
    amount = rng.uniform(40_000, 120_000)
    origin = b.person_account(rng)
    p = Pattern("peeling_chain", seed_account_id=origin.id, account_ids=[origin.id])
    p.path.append(origin.id)
    t = start
    p.transfer_ids.append(b.transfer(rng.choice(b.exchanges), origin, amount, t, "crypto").id)

    current = origin
    for _ in range(rng.randint(5, 7)):
        t += hours(rng.uniform(2, 20))
        peel = amount * rng.uniform(0.03, 0.08)
        cashout = b.person_account(rng)
        nxt = b.person_account(rng)
        p.transfer_ids.append(b.transfer(current, cashout, peel, t, "p2p").id)
        forward = amount - peel
        p.transfer_ids.append(b.transfer(current, nxt, forward, t + hours(rng.uniform(0.1, 2))).id)
        p.account_ids += [cashout.id, nxt.id]
        p.path.append(nxt.id)
        current, amount = nxt, forward
    return p


def fan_in_structuring(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Many mules each deposit just under the reporting threshold into one collector."""
    collector = b.person_account(rng)
    p = Pattern("fan_in_structuring", seed_account_id=collector.id, account_ids=[collector.id])
    total = 0.0
    last = start
    for _ in range(rng.randint(12, 20)):
        mule = b.person_account(rng, created_at=start - days(rng.uniform(20, 200)))
        amount = REPORTING_THRESHOLD * rng.uniform(0.82, 0.99)
        last = max(last, when := start + days(rng.uniform(0, 5)))
        p.transfer_ids.append(b.transfer(mule, collector, amount, when, "cash_deposit").id)
        p.account_ids.append(mule.id)
        total += amount
    exit_account = b.person_account(rng)
    p.transfer_ids.append(
        b.transfer(collector, exit_account, total * 0.97, last + hours(rng.uniform(4, 24))).id
    )
    p.account_ids.append(exit_account.id)
    return p


def fan_out(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """One large deposit is split across many fresh recipients within two days."""
    hub = b.person_account(rng)
    p = Pattern("fan_out", seed_account_id=hub.id, account_ids=[hub.id])
    amount = rng.uniform(30_000, 80_000)
    p.transfer_ids.append(b.transfer(rng.choice(b.exchanges), hub, amount, start, "crypto").id)

    n = rng.randint(10, 16)
    shares = [rng.uniform(0.5, 1.5) for _ in range(n)]
    payout = amount * rng.uniform(0.95, 0.99)
    for share in shares:
        recipient = b.person_account(rng)
        when = start + hours(rng.uniform(1, 36))
        p.transfer_ids.append(b.transfer(hub, recipient, payout * share / sum(shares), when).id)
        p.account_ids.append(recipient.id)
    return p


def round_trip(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Funds leave an account and come back to it within two weeks, losing only small fees."""
    members = [b.person_account(rng) for _ in range(rng.randint(3, 5))]
    origin = members[0]
    p = Pattern("round_trip", seed_account_id=origin.id, account_ids=[m.id for m in members])
    p.path = [m.id for m in members] + [origin.id]
    amount = rng.uniform(20_000, 60_000)
    t = start
    for src, dst in zip(members, members[1:] + [origin], strict=True):
        p.transfer_ids.append(b.transfer(src, dst, amount, t).id)
        amount *= rng.uniform(0.97, 0.995)
        t += days(rng.uniform(0.5, 3))
    return p


def rapid_layering(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Funds pass near-whole through freshly opened accounts within hours of arriving."""
    source = b.person_account(rng)
    intermediaries = [
        b.person_account(rng, created_at=start - days(rng.uniform(1, 10)))
        for _ in range(rng.randint(4, 6))
    ]
    destination = b.person_account(rng)
    route = [source, *intermediaries, destination]
    p = Pattern("rapid_layering", seed_account_id=source.id, account_ids=[a.id for a in route])
    p.path = [a.id for a in route]

    amount = rng.uniform(25_000, 90_000)
    t = start
    p.transfer_ids.append(b.transfer(rng.choice(b.exchanges), source, amount, t, "crypto").id)
    for src, dst in zip(route, route[1:], strict=False):
        t += hours(rng.uniform(0.5, 6))
        amount *= rng.uniform(0.97, 0.995)
        p.transfer_ids.append(b.transfer(src, dst, amount, t).id)
    return p


def shared_device(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Unrelated customers operate from one device and all pay the same destination."""
    device = b.device(rng)
    senders = [
        b.person_account(rng, created_at=start - days(rng.uniform(5, 30)))
        for _ in range(rng.randint(4, 6))
    ]
    destination = b.person_account(rng)
    p = Pattern(
        "shared_device",
        seed_account_id=senders[0].id,
        account_ids=[s.id for s in senders] + [destination.id],
        device_ids=[device.id],
    )
    for sender in senders:
        b.link(sender, device)
        when = start + days(rng.uniform(0, 3))
        p.transfer_ids.append(b.transfer(sender, destination, rng.uniform(3_000, 9_000), when).id)
    return p


def exit_via_mixer(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Funds hop through a few accounts, into a mixer, and out to an exchange."""
    source = b.person_account(rng)
    hops = [b.person_account(rng) for _ in range(rng.randint(2, 3))]
    mixer, exchange = rng.choice(b.mixers), rng.choice(b.exchanges)
    p = Pattern(
        "exit_via_mixer",
        seed_account_id=source.id,
        account_ids=[source.id] + [h.id for h in hops],
    )
    p.path = [source.id] + [h.id for h in hops] + [mixer.id, exchange.id]

    amount = rng.uniform(15_000, 70_000)
    t = start
    employer = rng.choice(b.employers)
    p.transfer_ids.append(b.transfer(employer, source, amount, t, "ach").id)
    route = [source, *hops, mixer, exchange]
    for src, dst in zip(route, route[1:], strict=False):
        t += hours(rng.uniform(3, 30))
        amount *= rng.uniform(0.9, 0.99)
        channel = "crypto" if dst.kind in ("mixer", "exchange") else "wire"
        p.transfer_ids.append(b.transfer(src, dst, amount, t, channel).id)
    return p


ALL = [
    peeling_chain,
    fan_in_structuring,
    fan_out,
    round_trip,
    rapid_layering,
    shared_device,
    exit_via_mixer,
]
