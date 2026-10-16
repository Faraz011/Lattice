"""Ordinary activity the patterns hide in: salaries, card spend, peer transfers, crypto buys.

Counterparties are drawn with Zipf-like weights so a few merchants and people are hubs,
giving the heavy-tailed degree distribution real payment graphs have.
"""

import random

from lattice.datagen.builder import WINDOW_DAYS, WINDOW_START, WorldBuilder, days, hours

EXCHANGES = ["CoinHarbor Exchange", "Bitvale Markets", "Northstar Crypto"]
MIXERS = ["Tumbler Pool A", "Tumbler Pool B"]


def _zipf_weights(n: int, exponent: float = 1.1) -> list[float]:
    return [1 / (rank**exponent) for rank in range(1, n + 1)]


def build_background(b: WorldBuilder, rng: random.Random, persons: int, businesses: int) -> None:
    b.exchanges = [b.business_account(rng, name, kind="exchange") for name in EXCHANGES]
    b.mixers = [b.business_account(rng, name, kind="mixer") for name in MIXERS]

    n_employers = max(1, businesses * 3 // 10)
    b.employers = [b.business_account(rng, f"Employer {i:03d} Ltd") for i in range(n_employers)]
    b.merchants = [
        b.business_account(rng, f"Merchant {i:03d}") for i in range(businesses - n_employers)
    ]

    for _ in range(persons):
        account = b.person_account(rng)
        for _ in range(rng.choice((1, 1, 2))):
            b.link(account, b.device(rng))
        b.persons.append(account)

    _salaries(b, rng)
    _card_spend(b, rng)
    _peer_transfers(b, rng)
    _crypto_buys(b, rng)


def _salaries(b: WorldBuilder, rng: random.Random) -> None:
    weights = _zipf_weights(len(b.employers))
    payday = {e.id: rng.randint(1, 28) for e in b.employers}
    for person in b.persons:
        employer = rng.choices(b.employers, weights)[0]
        salary = rng.uniform(1_800, 6_500)
        for month in range(3):
            when = WINDOW_START.replace(month=month + 1, day=payday[employer.id]) + hours(9)
            b.transfer(employer, person, salary, when, channel="ach", memo="salary")


def _card_spend(b: WorldBuilder, rng: random.Random) -> None:
    weights = _zipf_weights(len(b.merchants))
    for person in b.persons:
        for _ in range(rng.randint(3, 12)):
            merchant = rng.choices(b.merchants, weights)[0]
            when = WINDOW_START + days(rng.uniform(0, WINDOW_DAYS))
            b.transfer(person, merchant, rng.lognormvariate(3.6, 0.9), when, channel="card")


def _peer_transfers(b: WorldBuilder, rng: random.Random) -> None:
    hubs = b.persons[:]
    rng.shuffle(hubs)
    weights = _zipf_weights(len(hubs))
    for person in b.persons:
        for _ in range(rng.randint(0, 3)):
            peer = rng.choices(hubs, weights)[0]
            if peer.id == person.id:
                continue
            when = WINDOW_START + days(rng.uniform(0, WINDOW_DAYS))
            b.transfer(person, peer, rng.lognormvariate(4.8, 0.8), when, channel="p2p")


def _crypto_buys(b: WorldBuilder, rng: random.Random) -> None:
    for person in b.persons:
        if rng.random() < 0.1:
            when = WINDOW_START + days(rng.uniform(0, WINDOW_DAYS))
            b.transfer(person, rng.choice(b.exchanges), rng.uniform(200, 3_000), when, "crypto")
