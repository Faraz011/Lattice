"""Benign look-alikes (R1). Each shares its typology's surface shape but breaks a property
that separates laundering from ordinary business."""

import random
from datetime import datetime

from lattice.datagen.builder import WINDOW_START, Pattern, WorldBuilder, days, hours


def payroll_fan_out(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Like fan_out, but a business paying fixed salaries on the same day every month."""
    employer = b.business_account(rng, f"Workshop {rng.randint(100, 999)} GmbH")
    p = Pattern("payroll_fan_out", seed_account_id=employer.id, account_ids=[employer.id])
    payday = rng.randint(1, 28)
    for _ in range(rng.randint(10, 18)):
        employee = b.person_account(rng)
        salary = rng.uniform(2_500, 6_000)
        for month in range(1, 4):
            when = WINDOW_START.replace(month=month, day=payday) + hours(9)
            p.transfer_ids.append(b.transfer(employer, employee, salary, when, "ach").id)
        p.account_ids.append(employee.id)
    return p


def merchant_fan_in(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Like fan_in, but small varied card payments to a shop spread over two months."""
    merchant = b.business_account(rng, f"Corner Shop {rng.randint(100, 999)}")
    p = Pattern("merchant_fan_in", seed_account_id=merchant.id, account_ids=[merchant.id])
    for _ in range(rng.randint(25, 40)):
        customer = b.person_account(rng)
        for _ in range(rng.randint(1, 3)):
            when = WINDOW_START + days(rng.uniform(0, 70))
            amount = rng.uniform(5, 400)
            p.transfer_ids.append(b.transfer(customer, merchant, amount, when, "card").id)
        p.account_ids.append(customer.id)
    return p


def family_cycle(b: WorldBuilder, rng: random.Random, start: datetime) -> Pattern:
    """Like round_trip, but long-held family accounts moving unequal sums over weeks."""
    surname = rng.choice(["Okafor", "Novak", "Silva", "Larsen"])
    country = rng.choice(["GB", "DE", "PT"])
    created = start - days(rng.uniform(800, 2_000))
    members = [
        b.person_account(rng, created_at=created, country=country,
                         name=f"{first} {surname}")
        for first in rng.sample(["Ana", "Tomas", "Lina", "Joel", "Mira"], 3)
    ]
    p = Pattern("family_cycle", seed_account_id=members[0].id, account_ids=[m.id for m in members])
    p.path = [m.id for m in members] + [members[0].id]
    amounts = [rng.uniform(200, 400), rng.uniform(900, 1_500), rng.uniform(50, 150)]
    t = start
    for src, dst, amount in zip(members, members[1:] + members[:1], amounts, strict=True):
        p.transfer_ids.append(b.transfer(src, dst, amount, t, "p2p", memo="family").id)
        t += days(rng.uniform(8, 20))
    return p


ALL = [payroll_fan_out, merchant_fan_in, family_cycle]
