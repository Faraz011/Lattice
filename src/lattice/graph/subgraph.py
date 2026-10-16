"""The evidence graph the scorer reads: cited transfers and device links, plus their accounts.

It is loaded once (from Neo4j, or from a generated world in tests) and never touches the
database again. `without(...)` returns a cheap view with some edges removed, which is how the
evidence circuit (U12) ablates evidence thousands of times.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime

from lattice.graph.client import GraphClient
from lattice.graph.loader import GraphBatch
from lattice.ids import link_id


@dataclass(frozen=True)
class Transfer:
    id: str
    src: str
    dst: str
    amount: float
    ts: datetime
    channel: str


@dataclass(frozen=True)
class AccountInfo:
    id: str
    kind: str
    created_at: datetime
    customer_id: str


@dataclass(frozen=True)
class DeviceLink:
    id: str
    account_id: str
    device_id: str


@dataclass(frozen=True)
class EvidenceGraph:
    all_transfers: tuple[Transfer, ...]
    accounts: dict[str, AccountInfo]
    all_links: tuple[DeviceLink, ...]
    excluded: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(
        cls,
        transfers: list[Transfer],
        accounts: dict[str, AccountInfo],
        links: list[DeviceLink],
    ) -> "EvidenceGraph":
        ordered = tuple(sorted(transfers, key=lambda t: (t.ts, t.id)))
        return cls(ordered, dict(accounts), tuple(sorted(links, key=lambda link: link.id)))

    @classmethod
    def from_batch(cls, batch: GraphBatch, edge_ids: list[str]) -> "EvidenceGraph":
        """Evidence from a generated world, for tests and offline evaluation."""
        wanted = set(edge_ids)
        transfers = [
            Transfer(t.id, t.src, t.dst, t.amount, t.ts, t.channel)
            for t in batch.transfers if t.id in wanted
        ]
        links = [
            DeviceLink(link_id("USED_DEVICE", ad.account_id, ad.device_id), ad.account_id,
                       ad.device_id)
            for ad in batch.account_devices
            if link_id("USED_DEVICE", ad.account_id, ad.device_id) in wanted
        ]
        involved = {a for t in transfers for a in (t.src, t.dst)} | {
            link.account_id for link in links
        }
        accounts = {
            a.id: AccountInfo(a.id, a.kind, a.created_at, a.customer_id)
            for a in batch.accounts if a.id in involved
        }
        return cls.build(transfers, accounts, links)

    def transfers(self) -> list[Transfer]:
        return [t for t in self.all_transfers if t.id not in self.excluded]

    def links(self) -> list[DeviceLink]:
        return [link for link in self.all_links if link.id not in self.excluded]

    def edge_ids(self) -> list[str]:
        return [t.id for t in self.transfers()] + [link.id for link in self.links()]

    def without(self, edge_ids: set[str] | frozenset[str]) -> "EvidenceGraph":
        return replace(self, excluded=self.excluded | frozenset(edge_ids))

    def only(self, edge_ids: set[str] | frozenset[str]) -> "EvidenceGraph":
        keep = frozenset(edge_ids)
        return replace(self, excluded=frozenset(e for e in self.edge_ids() if e not in keep))

    def account(self, account_id: str) -> AccountInfo | None:
        return self.accounts.get(account_id)


async def load_evidence(graph: GraphClient, edge_ids: list[str]) -> EvidenceGraph:
    """Load cited transfers and device links, with every account they touch, from Neo4j."""
    transfer_ids = [e for e in edge_ids if e.startswith("tx_")]
    link_parts = [e.split(":") for e in edge_ids if e.startswith("used_device:")]

    rows = await graph.read(
        """
        MATCH (a:Account)-[t:TRANSFER]->(b:Account) WHERE t.id IN $ids
        RETURN t.id AS id, a.id AS src, b.id AS dst, t.amount AS amount, t.ts AS ts,
               t.channel AS channel
        """,
        ids=transfer_ids,
    )
    transfers = [
        Transfer(r["id"], r["src"], r["dst"], r["amount"], r["ts"].to_native(), r["channel"])
        for r in rows
    ]
    link_rows = await graph.read(
        """
        UNWIND $pairs AS pair
        MATCH (a:Account {id: pair[0]})-[:USED_DEVICE]->(d:Device {id: pair[1]})
        RETURN a.id AS account_id, d.id AS device_id
        """,
        pairs=[[parts[1], parts[2]] for parts in link_parts if len(parts) == 3],
    )
    links = [
        DeviceLink(link_id("USED_DEVICE", r["account_id"], r["device_id"]), r["account_id"],
                   r["device_id"])
        for r in link_rows
    ]
    involved = sorted({a for t in transfers for a in (t.src, t.dst)} | {
        link.account_id for link in links
    })
    account_rows = await graph.read(
        """
        MATCH (c:Customer)-[:OWNS]->(a:Account) WHERE a.id IN $ids
        RETURN a.id AS id, a.kind AS kind, a.created_at AS created_at, c.id AS customer_id
        """,
        ids=involved,
    )
    accounts = {
        r["id"]: AccountInfo(r["id"], r["kind"], r["created_at"].to_native(), r["customer_id"])
        for r in account_rows
    }
    return EvidenceGraph.build(transfers, accounts, links)
