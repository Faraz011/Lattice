"""What the UI reads: parsed case results, the ledger-backed evidence graph, and recordings."""

import json

import httpx
import pytest
from pydantic import SecretStr

from lattice.api.app import create_app
from lattice.config import load_settings
from lattice.ids import new_id


@pytest.fixture
def settings(keys):
    return load_settings().model_copy(update={
        "redis_namespace": keys.namespace,
        "approver_token": SecretStr("token-for-view-tests"),
        "max_active_cases": 1_000,
        "max_cases_per_day": 100_000,
    })


@pytest.fixture
def api(settings, fixture_world, serve_app):
    base, stop = serve_app(create_app(settings))
    yield base
    stop()


@pytest.fixture
async def case(api, graph, fixture_world):
    """A started case on a shared-device alert, removed with everything it created."""
    record = next(c for c in fixture_world.manifest.cases
                  if c.kind == "shared_device" and c.category == "planted")
    async with httpx.AsyncClient(base_url=api) as http:
        started = (await http.post(f"/alerts/{record.alert_id}/investigate")).json()["case"]
    yield started, record
    await graph.write(
        "MATCH (n) WHERE (n:Case AND n.id = $id) "
        "OR ((n:Action OR n:LedgerEntry OR n:Recording) AND n.case_id = $id) DETACH DELETE n",
        id=started["id"])


async def ledger(graph, case_id, tool, rel_ids):
    result_id = new_id("ledger")
    await graph.write(
        """
        CREATE (:LedgerEntry {result_id: $r, case_id: $c, tool: $tool, params: $params,
                              node_ids: [], rel_ids: $rels, ts: datetime()})
        """,
        r=result_id, c=case_id, tool=tool, params=json.dumps({"account_id": "x"}), rels=rel_ids)
    return result_id


async def get(api, path):
    async with httpx.AsyncClient(base_url=api) as http:
        return await http.get(path)


async def test_evidence_lists_every_ledgered_edge_with_the_calls_that_returned_it(
    api, graph, case, fixture_world
):
    started, record = case
    device_links = [f"used_device:{ad.account_id}:{ad.device_id}"
                    for ad in fixture_world.batch.account_devices
                    if ad.device_id in record.device_ids]
    first = await ledger(graph, started["id"], "graph_neighbors", record.transfer_ids[:2])
    second = await ledger(graph, started["id"], "algo_shared_attributes",
                          [record.transfer_ids[0], *device_links])

    evidence = (await get(api, f"/cases/{started['id']}/evidence")).json()

    edges = {e["id"]: e for e in evidence["edges"]}
    assert set(edges) == {*record.transfer_ids[:2], *device_links}
    assert edges[record.transfer_ids[0]]["sources"] == [first, second]
    assert edges[device_links[0]]["kind"] == "device_link"
    assert [e["id"] for e in evidence["edges"]][:2] == record.transfer_ids[:2]  # first seen first
    nodes = {n["id"]: n for n in evidence["nodes"]}
    assert record.seed_account_id in nodes
    assert {n["kind"] for n in nodes.values()} == {"account", "device"}
    assert evidence["ledger"][second]["tool"] == "algo_shared_attributes"
    assert evidence["ledger"][second]["params"] == {"account_id": "x"}


async def test_a_case_with_no_tool_calls_has_only_its_seed_account(api, case):
    started, record = case

    evidence = (await get(api, f"/cases/{started['id']}/evidence")).json()

    assert evidence["edges"] == []
    assert [n["id"] for n in evidence["nodes"]] == [record.seed_account_id]


async def test_case_results_are_returned_as_objects_not_json_strings(api, graph, case):
    started, _ = case
    await graph.write("MATCH (c:Case {id: $id}) SET c.verdict = $v, c.narrative = $n",
                      id=started["id"], v=json.dumps({"suspicious": True, "score": 0.8}),
                      n=json.dumps({"text": "t", "source": "template"}))

    body = (await get(api, f"/cases/{started['id']}")).json()

    assert body["case"]["verdict"] == {"suspicious": True, "score": 0.8}
    assert body["case"]["narrative"]["source"] == "template"
    assert "active_key" not in body["case"]


async def test_a_saved_recording_carries_events_and_a_snapshot_and_marks_the_alert(
    api, case
):
    started, record = case
    assert (await get(api, f"/cases/{started['id']}/recording")).status_code == 404

    async with httpx.AsyncClient(base_url=api) as http:
        saved = await http.post(f"/cases/{started['id']}/recording")

    assert saved.status_code == 201
    body = saved.json()
    assert [e["type"] for e in body["events"]] == ["case_started"]
    assert body["snapshot"]["case"]["id"] == started["id"]
    assert body["snapshot"]["evidence"]["nodes"][0]["id"] == record.seed_account_id
    alerts = (await get(api, "/alerts")).json()["alerts"]
    assert next(a for a in alerts if a["id"] == record.alert_id)["recorded_case_id"] == \
        started["id"]


async def test_evidence_for_an_unknown_case_is_not_found(api):
    assert (await get(api, "/cases/case_doesnotexist00/evidence")).status_code == 404
