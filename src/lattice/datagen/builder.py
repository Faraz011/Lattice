"""Shared world-building primitives used by background traffic, typologies and decoys.

Every pattern function receives its own `random.Random` and draws all randomness from it,
so calling it twice with the same seed reproduces the same structure under fresh IDs.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from lattice.graph.loader import (
    Account,
    AccountDevice,
    Customer,
    Device,
    GraphBatch,
    Transfer,
)
from lattice.ids import IdFactory

WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_DAYS = 90
REPORTING_THRESHOLD = 10_000.0

FIRST_NAMES = [
    "Ada", "Ben", "Chloe", "Dev", "Ema", "Femi", "Gus", "Hana", "Ivan", "Jade", "Kofi", "Lena",
    "Milo", "Nia", "Omar", "Pia", "Quinn", "Rosa", "Sami", "Tara", "Uma", "Vik", "Wen", "Yara",
]
LAST_NAMES = [
    "Adeyemi", "Brandt", "Costa", "Dubois", "Evans", "Fischer", "Garcia", "Haddad", "Ito",
    "Jansen", "Kowalski", "Larsen", "Moreau", "Novak", "Okafor", "Patel", "Rossi", "Silva",
]
COUNTRIES = ["GB", "DE", "FR", "NL", "ES", "IT", "PL", "IE", "PT", "SE"]


def hours(n: float) -> timedelta:
    return timedelta(hours=n)


def days(n: float) -> timedelta:
    return timedelta(days=n)


@dataclass
class Pattern:
    """What a typology or decoy planted: the exact members the manifest records."""

    kind: str
    seed_account_id: str
    account_ids: list[str] = field(default_factory=list)
    transfer_ids: list[str] = field(default_factory=list)
    device_ids: list[str] = field(default_factory=list)
    # Ordered route of the money where the pattern has one; used by tests, not the manifest.
    path: list[str] = field(default_factory=list)


class WorldBuilder:
    def __init__(self, seed: int) -> None:
        self.ids = IdFactory(seed)
        self.batch = GraphBatch()
        self.exchanges: list[Account] = []
        self.mixers: list[Account] = []
        self.employers: list[Account] = []
        self.merchants: list[Account] = []
        self.persons: list[Account] = []
        self._accounts: dict[str, Account] = {}
        self._transfers: dict[str, int] = {}

    # --- nodes -----------------------------------------------------------------------------

    def customer(
        self,
        rng: random.Random,
        kind: str = "person",
        name: str | None = None,
        country: str | None = None,
    ) -> Customer:
        if name is None:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        customer = Customer(
            id=self.ids.next("customer"),
            name=name,
            kind=kind,
            country=country or rng.choice(COUNTRIES),
        )
        self.batch.customers.append(customer)
        return customer

    def account(
        self,
        rng: random.Random,
        customer: Customer,
        kind: str | None = None,
        created_at: datetime | None = None,
    ) -> Account:
        account = Account(
            id=self.ids.next("account"),
            customer_id=customer.id,
            kind=kind or customer.kind,
            created_at=created_at or WINDOW_START - days(rng.uniform(365, 6 * 365)),
            country=customer.country,
        )
        self.batch.accounts.append(account)
        self._accounts[account.id] = account
        return account

    def person_account(
        self,
        rng: random.Random,
        created_at: datetime | None = None,
        name: str | None = None,
        country: str | None = None,
    ) -> Account:
        customer = self.customer(rng, "person", name=name, country=country)
        return self.account(rng, customer, created_at=created_at)

    def business_account(
        self, rng: random.Random, name: str, kind: str = "business"
    ) -> Account:
        customer = self.customer(rng, "business", name=name)
        return self.account(rng, customer, kind=kind)

    def device(self, rng: random.Random) -> Device:
        device = Device(id=self.ids.next("device"), fingerprint=f"fp-{rng.getrandbits(48):012x}")
        self.batch.devices.append(device)
        return device

    def link(self, account: Account, device: Device) -> None:
        self.batch.account_devices.append(AccountDevice(account_id=account.id, device_id=device.id))

    # --- transfers -------------------------------------------------------------------------

    def transfer(
        self,
        src: Account,
        dst: Account,
        amount: float,
        ts: datetime,
        channel: str = "wire",
        memo: str | None = None,
    ) -> Transfer:
        transfer = Transfer(
            id=self.ids.next("transfer"),
            src=src.id,
            dst=dst.id,
            amount=round(amount, 2),
            ts=ts,
            channel=channel,
            memo=memo,
        )
        self._transfers[transfer.id] = len(self.batch.transfers)
        self.batch.transfers.append(transfer)
        return transfer

    def set_memo(self, transfer_id: str, memo: str) -> None:
        index = self._transfers[transfer_id]
        self.batch.transfers[index] = self.batch.transfers[index].model_copy(update={"memo": memo})

    # --- lookups ---------------------------------------------------------------------------

    def account_by_id(self, account_id: str) -> Account:
        return self._accounts[account_id]

    def transfer_by_id(self, transfer_id: str) -> Transfer:
        return self.batch.transfers[self._transfers[transfer_id]]
