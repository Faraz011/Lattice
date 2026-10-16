"""The API and the action executor against compose Neo4j and Redis, over real HTTP."""

import asyncio
import json
import uuid

import httpx
import pytest
from pydantic import SecretStr

from lattice.api.app import create_app
from lattice.cases.actions import ActionStore
from lattice.cases.store import CaseStore
from lattice.config import load_settings
from lattice.mcp_server.tools_case import propose_action
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.workers.action_worker import make_handler

TOKEN = "approver-secret-for-tests"


@pytest.fixture
def settings(keys):
    return load_settings().model_copy(update={
        "redis_namespace": keys.namespace,
        "approver_token": SecretStr(TOKEN),
        "max_active_cases": 1_000,
        "max_cases_per_day": 100_000,
    })


@pytest.fixture
def api(settings, fixture_world, serve_app):
    base, stop = serve_app(create_app(settings))
    yield base
    stop()


@pytest.fixture
async def created(graph):
    """Case IDs a test created; removed with their actions afterwards."""
    ids: list[str] = []
    yield ids
    await graph.write(
        "MATCH (n) WHERE (n:Case AND n.id IN $ids) "
        "OR ((n:Action OR n:LedgerEntry OR n:Recording) AND n.case_id IN $ids) "
        "DETACH DELETE n", ids=ids)


def alert_of(world, kind, category="planted"):
    return next(c for c in world.manifest.cases if c.kind == kind and c.category == category)


async def start(api, alert_id, created, **body):
    async with httpx.AsyncClient(base_url=api) as http:
        response = await http.post(f"/alerts/{alert_id}/investigate", json=body)
    if response.status_code in (200, 201):
        created.append(response.json()["case"]["id"])
    return response


async def jobs(redis_client, keys, job_type):
    return [Job.from_fields(f) for _, f in await redis_client.xrange(keys.stream(job_type))]


async def proposed_freeze(graph, case_id, target, with_blast_radius=True):
    proposal = await propose_action(graph, case_id, "freeze", target, "peeling chain")
    if with_blast_radius:
        await ActionStore(graph).set_blast_radius(proposal.action_id,
                                                  {"account_count": 7, "customer_count": 7})
    return proposal.action_id


# --- starting investigations --------------------------------------------------------------


async def test_starting_an_investigation_creates_a_received_case_and_one_job(
    api, fixture_world, created, redis_client, keys
):
    record = alert_of(fixture_world, "fan_out")

    response = await start(api, record.alert_id, created)

    assert response.status_code == 201
    case = response.json()["case"]
    assert case["status"] == "received"
    assert case["seed_account_id"] == record.seed_account_id
    queued = await jobs(redis_client, keys, "hypothesis")
    assert len(queued) == 1
    assert queued[0].payload["brief"]["hypothesis"] == "open"
    assert queued[0].payload["single_agent"] is True


async def test_starting_twice_returns_the_same_active_case_and_one_job(
    api, fixture_world, created, redis_client, keys
):
    record = alert_of(fixture_world, "round_trip")

    first = await start(api, record.alert_id, created)
    second = await start(api, record.alert_id, created)

    assert second.status_code == 200
    assert second.json()["case"]["id"] == first.json()["case"]["id"]
    assert len(await jobs(redis_client, keys, "hypothesis")) == 1


async def test_past_the_active_case_cap_a_new_investigation_is_refused(
    settings, fixture_world, created, graph, serve_app
):
    active = (await graph.read(
        "MATCH (c:Case) WHERE c.active_key IS NOT NULL RETURN count(c) AS n"))[0]["n"]
    refused_alert = alert_of(fixture_world, "peeling_chain").alert_id
    count = "MATCH (c:Case {alert_id: $a}) RETURN count(c) AS n"
    before = (await graph.read(count, a=refused_alert))[0]["n"]
    base, stop = serve_app(create_app(settings.model_copy(
        update={"max_active_cases": active + 1})))
    try:
        allowed = await start(base, alert_of(fixture_world, "fan_in_structuring").alert_id,
                              created)
        refused = await start(base, refused_alert, created)
    finally:
        stop()

    assert allowed.status_code == 201
    assert refused.status_code == 429
    assert (await graph.read(count, a=refused_alert))[0]["n"] == before


async def test_an_unknown_alert_is_not_found(api, created):
    response = await start(api, "alert_doesnotexist000", created)

    assert response.status_code == 404


async def test_alerts_are_listed_with_their_seed_accounts(api, fixture_world):
    async with httpx.AsyncClient(base_url=api) as http:
        alerts = (await http.get("/alerts")).json()["alerts"]

    by_id = {a["id"]: a for a in alerts}
    record = alert_of(fixture_world, "fan_out")
    assert by_id[record.alert_id]["seed_account_id"] == record.seed_account_id


# --- approvals and the executor -----------------------------------------------------------


async def test_approving_without_the_token_is_unauthorized_and_changes_nothing(
    api, fixture_world, created, graph
):
    case_id = (await start(api, alert_of(fixture_world, "peeling_chain").alert_id,
                           created)).json()["case"]["id"]
    action_id = await proposed_freeze(graph, case_id, alert_of(fixture_world,
                                                               "peeling_chain").seed_account_id)

    async with httpx.AsyncClient(base_url=api) as http:
        missing = await http.post(f"/actions/{action_id}/approve")
        wrong = await http.post(f"/actions/{action_id}/approve",
                                headers={"X-Approver-Token": "guess"})

    assert missing.status_code == wrong.status_code == 401
    assert (await ActionStore(graph).get(action_id))["status"] == "proposed"


async def test_a_tier_three_action_cannot_be_approved_before_its_blast_radius_exists(
    api, fixture_world, created, graph
):
    record = alert_of(fixture_world, "peeling_chain")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    action_id = await proposed_freeze(graph, case_id, record.seed_account_id,
                                      with_blast_radius=False)

    async with httpx.AsyncClient(base_url=api) as http:
        response = await http.post(f"/actions/{action_id}/approve",
                                   headers={"X-Approver-Token": TOKEN})

    assert response.status_code == 409
    assert (await ActionStore(graph).get(action_id))["status"] == "proposed"


async def test_an_approved_action_is_queued_and_the_executor_records_it(
    api, settings, fixture_world, created, graph, redis_client, keys
):
    record = alert_of(fixture_world, "peeling_chain")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    cases = CaseStore(graph)
    for status in ("investigating", "verifying", "awaiting_approval"):
        await cases.transition(case_id, status, "test")
    action_id = await proposed_freeze(graph, case_id, record.seed_account_id)

    async with httpx.AsyncClient(base_url=api) as http:
        response = await http.post(f"/actions/{action_id}/approve",
                                   headers={"X-Approver-Token": TOKEN})
    assert response.status_code == 200
    assert (await ActionStore(graph).get(action_id))["status"] == "approved"
    (job,) = await jobs(redis_client, keys, "execute_action")

    events = EventStream(redis_client, keys)
    await make_handler(graph, events)(job)

    action = await ActionStore(graph).get(action_id)
    assert action["status"] == "executed"
    assert "frozen" in action["outcome"]
    assert (await cases.get(case_id))["status"] == "actioned"
    assert "action_executed" in [e.type for e in await events.read_all(case_id)]


async def test_a_tier_one_annotation_executes_without_approval(
    api, fixture_world, created, graph, redis_client, keys
):
    record = alert_of(fixture_world, "fan_out")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    proposal = await propose_action(graph, case_id, "annotate", record.seed_account_id, "note")

    events = EventStream(redis_client, keys)
    await make_handler(graph, events)(Job.new("execute_action", case_id,
                                              {"action_id": proposal.action_id}))

    assert (await ActionStore(graph).get(proposal.action_id))["status"] == "executed"


async def test_an_unapproved_action_sent_straight_to_the_executor_is_refused(
    api, fixture_world, created, graph, redis_client, keys
):
    record = alert_of(fixture_world, "peeling_chain")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    action_id = await proposed_freeze(graph, case_id, record.seed_account_id)

    events = EventStream(redis_client, keys)
    await make_handler(graph, events)(Job.new("execute_action", case_id,
                                              {"action_id": action_id}))

    action = await ActionStore(graph).get(action_id)
    assert action["status"] == "refused"
    assert "approval" in action["refusal_reason"]
    assert "action_refused" in [e.type for e in await events.read_all(case_id)]


async def test_rejecting_an_action_records_it_and_nothing_executes(
    api, fixture_world, created, graph, redis_client, keys
):
    record = alert_of(fixture_world, "peeling_chain")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    action_id = await proposed_freeze(graph, case_id, record.seed_account_id)

    async with httpx.AsyncClient(base_url=api) as http:
        response = await http.post(f"/actions/{action_id}/reject",
                                   headers={"X-Approver-Token": TOKEN}, json={"reason": "no"})

    assert response.status_code == 200
    assert (await ActionStore(graph).get(action_id))["status"] == "rejected"
    assert await jobs(redis_client, keys, "execute_action") == []


# --- review decisions ---------------------------------------------------------------------


async def test_clearing_a_review_case_needs_the_token(api, fixture_world, created, graph):
    record = alert_of(fixture_world, "fan_in_structuring")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    cases = CaseStore(graph)
    await cases.transition(case_id, "investigating", "test")
    await cases.transition(case_id, "needs_review", "budget exhausted")

    async with httpx.AsyncClient(base_url=api) as http:
        refused = await http.post(f"/cases/{case_id}/clear")
        cleared = await http.post(f"/cases/{case_id}/clear", headers={"X-Approver-Token": TOKEN})

    assert refused.status_code == 401
    assert cleared.status_code == 200
    assert (await cases.get(case_id))["status"] == "closed_no_action"


async def test_escalating_a_review_case_proposes_an_action_to_approve(
    api, fixture_world, created, graph
):
    record = alert_of(fixture_world, "peeling_chain")
    case_id = (await start(api, record.alert_id, created)).json()["case"]["id"]
    cases = CaseStore(graph)
    await cases.transition(case_id, "investigating", "test")
    await cases.transition(case_id, "needs_review", "investigators and scorer disagree")

    async with httpx.AsyncClient(base_url=api) as http:
        escalated = await http.post(f"/cases/{case_id}/escalate",
                                    headers={"X-Approver-Token": TOKEN})
        again = await http.post(f"/cases/{case_id}/escalate",
                                headers={"X-Approver-Token": TOKEN})

    assert escalated.status_code == 200
    assert again.status_code == 409
    assert (await cases.get(case_id))["status"] == "awaiting_approval"
    (action,) = await ActionStore(graph).for_case(case_id)
    assert action["status"] == "proposed"
    assert action["kind"] == "escalate"  # no suspicious verdict: escalate, not freeze
    assert action["target_id"] == record.seed_account_id
    assert action["blast_radius"]["account_count"] > 0


async def test_a_closed_case_frees_its_alert_for_a_new_investigation(
    api, fixture_world, created, graph
):
    record = alert_of(fixture_world, "round_trip")
    first = (await start(api, record.alert_id, created)).json()["case"]["id"]
    cases = CaseStore(graph)
    await cases.transition(first, "investigating", "test")
    await cases.transition(first, "needs_review", "test")
    await cases.transition(first, "closed_no_action", "cleared")

    second = await start(api, record.alert_id, created)

    assert second.status_code == 201
    assert second.json()["case"]["id"] != first


# --- server-sent events -------------------------------------------------------------------


async def test_the_event_stream_replays_earlier_events_then_follows_live_ones(
    api, created, redis_client, keys
):
    case_id = f"case_sse{uuid.uuid4().hex[:10]}"
    events = EventStream(redis_client, keys)
    for i in range(3):
        await events.publish(case_id, "tool_called", {"n": i})

    received: list[dict] = []

    async def listen():
        async with httpx.AsyncClient(base_url=api, timeout=10) as http, http.stream(
            "GET", f"/cases/{case_id}/events"
        ) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    received.append(json.loads(line[5:]))
                    if len(received) == 4:
                        return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0.5)
    await events.publish(case_id, "finding", {"n": 3})
    await asyncio.wait_for(listener, timeout=10)

    assert [e["data"]["n"] for e in received] == [0, 1, 2, 3]
    assert [e["type"] for e in received] == ["tool_called"] * 3 + ["finding"]
