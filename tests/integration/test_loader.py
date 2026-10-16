"""Loader tests against the compose Neo4j. Each test uses a fresh seed and removes what it wrote."""

import uuid
from datetime import UTC, datetime

import pytest
from neo4j.exceptions import ConstraintError

from lattice.config import load_settings
from lattice.graph.client import GraphClient
from lattice.graph.loader import (
    Account,
    AccountDevice,
    Alert,
    Customer,
    Device,
    GraphBatch,
    LoaderError,
    Transfer,
    load_batch,
)
from lattice.graph.schema import apply_schema
from lattice.ids import IdFactory


@pytest.fixture
async def client():
    async with GraphClient.from_settings(load_settings()) as graph:
        await apply_schema(graph)
        yield graph


def make_batch(seed: int) -> GraphBatch:
    ids = IdFactory(seed=seed)
    cust_a, cust_b = ids.next("customer"), ids.next("customer")
    acct_a, acct_b, acct_c = ids.next("account"), ids.next("account"), ids.next("account")
    device = ids.next("device")
    when = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    return GraphBatch(
        customers=[
            Customer(id=cust_a, name="Ada", kind="person", country="GB"),
            Customer(id=cust_b, name="Bo Ltd", kind="business", country="DE"),
        ],
        accounts=[
            Account(id=acct_a, customer_id=cust_a, kind="person", created_at=when, country="GB"),
            Account(id=acct_b, customer_id=cust_b, kind="business", created_at=when, country="DE"),
            Account(id=acct_c, customer_id=cust_b, kind="business", created_at=when, country="DE"),
        ],
        devices=[Device(id=device, fingerprint="fp-1")],
        account_devices=[AccountDevice(account_id=acct_a, device_id=device)],
        transfers=[
            Transfer(id=ids.next("transfer"), src=acct_a, dst=acct_b, amount=950.0, ts=when,
                     channel="wire", memo="invoice 17"),
            Transfer(id=ids.next("transfer"), src=acct_b, dst=acct_c, amount=900.0, ts=when,
                     channel="wire", memo=None),
        ],
        alerts=[Alert(id=ids.next("alert"), seed_account_id=acct_a, reason="test", ts=when)],
    )


async def count(graph: GraphClient, batch: GraphBatch) -> tuple[int, int]:
    node_ids = batch.node_ids()
    rel_ids = [t.id for t in batch.transfers]
    rows = await graph.read(
        """
        MATCH (n) WHERE n.id IN $node_ids WITH count(n) AS nodes
        OPTIONAL MATCH ()-[r]->() WHERE r.id IN $rel_ids OR
          (type(r) IN ['OWNS', 'USED_DEVICE'] AND startNode(r).id IN $node_ids)
        RETURN nodes, count(r) AS rels
        """,
        node_ids=node_ids,
        rel_ids=rel_ids,
    )
    return rows[0]["nodes"], rows[0]["rels"]


async def remove(graph: GraphClient, batch: GraphBatch) -> None:
    await graph.write("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=batch.node_ids())


async def test_loading_the_same_batch_twice_changes_nothing(client):
    batch = make_batch(seed=uuid.uuid4().int)
    try:
        await load_batch(client, batch)
        first = await count(client, batch)
        await load_batch(client, batch)
        second = await count(client, batch)
    finally:
        await remove(client, batch)

    # 2 customers + 3 accounts + 1 device + 1 alert; 2 transfers + 3 OWNS + 1 USED_DEVICE
    assert first == (7, 6)
    assert second == first


async def test_a_loaded_transfer_is_fetched_by_its_id_with_matching_endpoints(client):
    batch = make_batch(seed=uuid.uuid4().int)
    transfer = batch.transfers[0]
    try:
        await load_batch(client, batch)
        rows = await client.read(
            "MATCH (a)-[t:TRANSFER {id: $id}]->(b) "
            "RETURN a.id AS src, b.id AS dst, t.amount AS amount, t.memo AS memo",
            id=transfer.id,
        )
    finally:
        await remove(client, batch)

    expected = {"src": transfer.src, "dst": transfer.dst, "amount": 950.0, "memo": "invoice 17"}
    assert rows == [expected]


async def test_a_batch_with_a_duplicate_account_id_is_rejected_naming_the_id(client):
    batch = make_batch(seed=uuid.uuid4().int)
    duplicate = batch.accounts[0].model_copy(update={"country": "FR"})
    batch.accounts.append(duplicate)

    with pytest.raises(LoaderError, match=duplicate.id):
        await load_batch(client, batch)

    nodes, _ = await count(client, batch)
    assert nodes == 0  # rejected before anything was written


async def test_the_account_id_constraint_rejects_a_second_node_with_the_same_id(client):
    account_id = IdFactory(seed=uuid.uuid4().int).next("account")
    try:
        await client.write("CREATE (:Account {id: $id})", id=account_id)
        with pytest.raises(ConstraintError, match=account_id):
            await client.write("CREATE (:Account {id: $id})", id=account_id)
    finally:
        await client.write("MATCH (a:Account {id: $id}) DETACH DELETE a", id=account_id)


async def test_a_transfer_id_reused_between_different_accounts_is_rejected(client):
    batch = make_batch(seed=uuid.uuid4().int)
    try:
        await load_batch(client, batch)
        reused = batch.transfers[0].model_copy(
            update={"src": batch.accounts[1].id, "dst": batch.accounts[2].id}
        )
        with pytest.raises(ConstraintError, match=reused.id):
            await load_batch(client, GraphBatch(transfers=[reused]))
    finally:
        await remove(client, batch)


async def test_a_transfer_to_an_unknown_account_is_rejected_naming_it(client):
    ids = IdFactory(seed=uuid.uuid4().int)
    orphan = Transfer(id=ids.next("transfer"), src=ids.next("account"), dst=ids.next("account"),
                      amount=1.0, ts=datetime(2026, 1, 1, tzinfo=UTC), channel="wire", memo=None)

    with pytest.raises(LoaderError, match=orphan.id):
        await load_batch(client, GraphBatch(transfers=[orphan]))


async def test_schema_constraints_exist_after_apply(client):
    rows = await client.read("SHOW CONSTRAINTS YIELD labelsOrTypes, properties")
    present = {(tuple(r["labelsOrTypes"]), tuple(r["properties"])) for r in rows}

    for label in ("Customer", "Account", "Device", "Alert", "Case", "Action", "Recording"):
        assert ((label,), ("id",)) in present
    assert (("LedgerEntry",), ("result_id",)) in present
    assert (("TRANSFER",), ("id",)) in present
