"""Idempotent batch loader for transaction data.

Reloading the same records changes nothing, because every write MERGEs on the stable ID.
A batch that contradicts itself (one ID used twice) or points at accounts that do not exist
is rejected before anything is written.
"""

from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from lattice.graph.client import GraphClient
from lattice.graph.schema import OWNS, TRANSFER, USED_DEVICE

BATCH_SIZE = 5_000


class LoaderError(ValueError):
    """The batch is inconsistent and was not written."""


class Customer(BaseModel):
    id: str
    name: str
    kind: Literal["person", "business"]
    country: str


class Account(BaseModel):
    id: str
    customer_id: str
    kind: Literal["person", "business", "exchange", "mixer"]
    created_at: datetime
    country: str


class Device(BaseModel):
    id: str
    fingerprint: str


class AccountDevice(BaseModel):
    account_id: str
    device_id: str


class Transfer(BaseModel):
    id: str
    src: str
    dst: str
    amount: float
    ts: datetime
    channel: str
    memo: str | None = None


class Alert(BaseModel):
    id: str
    seed_account_id: str
    reason: str
    ts: datetime


class GraphBatch(BaseModel):
    customers: list[Customer] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    devices: list[Device] = Field(default_factory=list)
    account_devices: list[AccountDevice] = Field(default_factory=list)
    transfers: list[Transfer] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)

    def node_ids(self) -> list[str]:
        nodes = [*self.customers, *self.accounts, *self.devices, *self.alerts]
        return [node.id for node in nodes]


async def load_batch(graph: GraphClient, batch: GraphBatch) -> None:
    _reject_duplicate_ids(batch)
    await _reject_unknown_references(graph, batch)

    await _write(graph, "MERGE (c:Customer {id: row.id}) SET c += row", batch.customers)
    await _write(
        graph,
        f"""
        MERGE (a:Account {{id: row.id}})
        SET a.kind = row.kind, a.created_at = row.created_at, a.country = row.country
        WITH a, row
        MATCH (c:Customer {{id: row.customer_id}})
        MERGE (c)-[:{OWNS}]->(a)
        """,
        batch.accounts,
    )
    await _write(graph, "MERGE (d:Device {id: row.id}) SET d += row", batch.devices)
    await _write(
        graph,
        f"""
        MATCH (a:Account {{id: row.account_id}})
        MATCH (d:Device {{id: row.device_id}})
        MERGE (a)-[:{USED_DEVICE}]->(d)
        """,
        batch.account_devices,
    )
    await _write(
        graph,
        f"""
        MATCH (a:Account {{id: row.src}})
        MATCH (b:Account {{id: row.dst}})
        MERGE (a)-[t:{TRANSFER} {{id: row.id}}]->(b)
        SET t.amount = row.amount, t.ts = row.ts, t.channel = row.channel, t.memo = row.memo
        """,
        batch.transfers,
    )
    await _write(graph, "MERGE (al:Alert {id: row.id}) SET al += row", batch.alerts)


def _reject_duplicate_ids(batch: GraphBatch) -> None:
    for name, ids in (
        ("node", batch.node_ids()),
        ("transfer", [t.id for t in batch.transfers]),
    ):
        repeated = sorted(i for i, n in Counter(ids).items() if n > 1)
        if repeated:
            raise LoaderError(f"duplicate {name} id(s) in batch: {', '.join(repeated)}")


async def _reject_unknown_references(graph: GraphClient, batch: GraphBatch) -> None:
    known_accounts = await _known(graph, "Account", _account_refs(batch), batch.accounts)
    known_customers = await _known(
        graph, "Customer", [a.customer_id for a in batch.accounts], batch.customers
    )
    known_devices = await _known(
        graph, "Device", [link.device_id for link in batch.account_devices], batch.devices
    )

    problems = [
        f"transfer {t.id} references unknown account {ref}"
        for t in batch.transfers
        for ref in (t.src, t.dst)
        if ref not in known_accounts
    ]
    problems += [
        f"account {a.id} references unknown customer {a.customer_id}"
        for a in batch.accounts
        if a.customer_id not in known_customers
    ]
    problems += [
        f"device link {link.account_id}->{link.device_id} references an unknown node"
        for link in batch.account_devices
        if link.account_id not in known_accounts or link.device_id not in known_devices
    ]
    problems += [
        f"alert {al.id} references unknown account {al.seed_account_id}"
        for al in batch.alerts
        if al.seed_account_id not in known_accounts
    ]
    if problems:
        raise LoaderError("batch references missing nodes:\n  " + "\n  ".join(problems))


def _account_refs(batch: GraphBatch) -> list[str]:
    refs = [ref for t in batch.transfers for ref in (t.src, t.dst)]
    refs += [link.account_id for link in batch.account_devices]
    refs += [al.seed_account_id for al in batch.alerts]
    return refs


async def _known(
    graph: GraphClient, label: str, refs: Iterable[str], in_batch: Iterable[BaseModel]
) -> set[str]:
    known = {node.id for node in in_batch}
    missing = sorted(set(refs) - known)
    if missing:
        rows = await graph.read(
            f"MATCH (n:{label}) WHERE n.id IN $ids RETURN n.id AS id", ids=missing
        )
        known |= {row["id"] for row in rows}
    return known


async def _write(graph: GraphClient, statement: str, items: list[BaseModel]) -> None:
    for chunk in _chunks(items):
        rows = [item.model_dump() for item in chunk]
        await graph.write(f"UNWIND $rows AS row {statement}", rows=rows)


def _chunks(items: list[BaseModel]) -> Iterator[list[BaseModel]]:
    for start in range(0, len(items), BATCH_SIZE):
        yield items[start : start + BATCH_SIZE]
