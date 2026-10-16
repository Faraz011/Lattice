"""Fan-out, fan-in, deadlines and the sweeper, against compose Neo4j and Redis."""

import asyncio
import time

import pytest
from test_investigator_flow import scripted

from lattice.agents.investigator import investigate
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Finding
from lattice.cases.actions import ActionStore
from lattice.cases.store import CaseStore
from lattice.config import load_settings
from lattice.mcp_server.tools_case import propose_action
from lattice.queue.events import EventStream
from lattice.queue.fanin import FanIn
from lattice.queue.jobs import Job
from lattice.queue.streams import Consumer, JobQueue
from lattice.workers import orchestrator_worker, verifier_worker
from lattice.workers.investigator_worker import make_handler as investigator_handler
from lattice.workers.sweeper import Sweeper


def finding(hypothesis, verdict="refutes"):
    return Finding(hypothesis=hypothesis, verdict=verdict, confidence=0.7, summary="s",
                   claims=[])


@pytest.fixture
async def cases(graph):
    created: list[str] = []

    async def start(record, mode="orchestrated"):
        case, _ = await CaseStore(graph).start(record.alert_id, mode, 10_000, 100_000)
        created.append(case["id"])
        return case

    yield start
    await graph.write(
        "MATCH (n) WHERE (n:Case AND n.id IN $ids) OR ((n:Action OR n:LedgerEntry OR n:Recording) "
        "AND n.case_id IN $ids) DETACH DELETE n", ids=created)


def record_of(world, kind):
    return next(c for c in world.manifest.cases
                if c.kind == kind and c.category == "planted" and not c.case_id.endswith("twin"))


async def queued(redis_client, keys, job_type):
    return [Job.from_fields(f) for _, f in await redis_client.xrange(keys.stream(job_type))]


# --- fan-in ---------------------------------------------------------------------------------


async def test_concurrent_last_findings_hand_off_exactly_once(redis_client, keys):
    fanin = FanIn(redis_client, keys)
    await fanin.open("case_f1", ["peeling_chain", "fan_out", "round_trip"], deadline_s=60)

    results = await asyncio.gather(*(fanin.record("case_f1", h, finding(h))
                                     for h in ("peeling_chain", "fan_out", "round_trip")))

    assert sum(1 for ready in results if ready) == 1
    collected = await fanin.collect("case_f1")
    assert sorted(f.hypothesis for f in collected) == ["fan_out", "peeling_chain", "round_trip"]


async def test_a_duplicate_finding_does_not_complete_the_fan_in_early(redis_client, keys):
    fanin = FanIn(redis_client, keys)
    await fanin.open("case_f2", ["peeling_chain", "fan_out"], deadline_s=60)

    first = await fanin.record("case_f2", "peeling_chain", finding("peeling_chain"))
    duplicate = await fanin.record("case_f2", "peeling_chain", finding("peeling_chain"))
    last = await fanin.record("case_f2", "fan_out", finding("fan_out"))

    assert (first, duplicate, last) == (False, False, True)


# --- the sweeper ----------------------------------------------------------------------------


async def test_a_missed_deadline_verifies_with_what_arrived_and_notes_the_gap(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "fan_out"))
    fanin = FanIn(redis_client, keys)
    await fanin.open(case["id"], ["fan_out", "peeling_chain", "round_trip"], deadline_s=0)
    await fanin.record(case["id"], "fan_out", finding("fan_out"))
    await fanin.record(case["id"], "round_trip", finding("round_trip"))
    sweeper = Sweeper(graph, redis_client, keys, load_settings())

    await sweeper.sweep_once()
    await sweeper.sweep_once()

    (verify,) = await queued(redis_client, keys, "verify")
    findings = [Finding.model_validate(f) for f in verify.payload["findings"]]
    missing = next(f for f in findings if f.hypothesis == "peeling_chain")
    assert missing.status == "failed"
    assert "deadline" in missing.status_reason
    saved = await CaseStore(graph).saved_findings(case["id"])
    assert len(saved) == 3


async def test_a_case_whose_fan_in_was_lost_is_redispatched_from_neo4j(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "fan_out"))
    store = CaseStore(graph)
    await store.transition(case["id"], "planning", "test")
    await store.transition(case["id"], "investigating", "test")
    await graph.write("MATCH (c:Case {id: $id}) SET c.updated_at = datetime() - duration('PT1H')",
                      id=case["id"])

    await Sweeper(graph, redis_client, keys, load_settings()).sweep_once()

    (job,) = await queued(redis_client, keys, "investigate")
    assert job.case_id == case["id"]


async def test_a_case_lost_while_verifying_is_verified_from_its_saved_findings(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "fan_out"))
    store = CaseStore(graph)
    for status in ("investigating", "verifying"):
        await store.transition(case["id"], status, "test")
    await store.save_findings(case["id"], [finding("fan_out")])
    await graph.write("MATCH (c:Case {id: $id}) SET c.updated_at = datetime() - duration('PT1H')",
                      id=case["id"])

    await Sweeper(graph, redis_client, keys, load_settings()).sweep_once()
    (verify,) = await queued(redis_client, keys, "verify")
    await verifier_worker.make_handler(graph, EventStream(redis_client, keys),
                                       load_settings())(verify)

    assert (await store.get(case["id"]))["status"] in ("closed_no_action", "needs_review")


async def test_a_handed_off_fan_in_whose_verify_job_was_lost_is_verified_again(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "fan_out"))
    store = CaseStore(graph)
    for status in ("planning", "investigating"):
        await store.transition(case["id"], status, "test")
    fanin = FanIn(redis_client, keys)
    await fanin.open(case["id"], ["fan_out"], deadline_s=300)
    assert await fanin.record(case["id"], "fan_out", finding("fan_out"))  # hand-off claimed
    await store.save_findings(case["id"], [finding("fan_out")])
    # ...but the verify job never ran (dead-lettered, or lost with Redis).
    await graph.write("MATCH (c:Case {id: $id}) SET c.updated_at = datetime() - duration('PT1H')",
                      id=case["id"])

    await Sweeper(graph, redis_client, keys, load_settings()).sweep_once()

    (verify,) = await queued(redis_client, keys, "verify")
    assert verify.case_id == case["id"]
    assert await queued(redis_client, keys, "investigate") == []


async def test_a_fan_in_still_collecting_is_left_to_its_deadline(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "fan_out"))
    store = CaseStore(graph)
    for status in ("planning", "investigating"):
        await store.transition(case["id"], status, "test")
    await FanIn(redis_client, keys).open(case["id"], ["fan_out", "peeling_chain"], 300)
    await graph.write("MATCH (c:Case {id: $id}) SET c.updated_at = datetime() - duration('PT1H')",
                      id=case["id"])

    await Sweeper(graph, redis_client, keys, load_settings()).sweep_once()

    assert await queued(redis_client, keys, "verify") == []
    assert await queued(redis_client, keys, "investigate") == []


async def test_an_approved_action_that_never_ran_is_requeued(
    graph, redis_client, keys, fixture_world, cases
):
    record = record_of(fixture_world, "peeling_chain")
    case = await cases(record)
    proposal = await propose_action(graph, case["id"], "freeze", record.seed_account_id, "x")
    actions = ActionStore(graph)
    await actions.set_blast_radius(proposal.action_id, {"account_count": 1})
    await actions.approve(proposal.action_id, "tester")
    await graph.write("MATCH (a:Action {id: $id}) SET a.updated_at = datetime() - duration('PT1H')",
                      id=proposal.action_id)

    await Sweeper(graph, redis_client, keys, load_settings()).sweep_once()

    (job,) = await queued(redis_client, keys, "execute_action")
    assert job.payload["action_id"] == proposal.action_id


# --- the whole orchestrated path ----------------------------------------------------------


async def test_orchestrated_peeling_chain_runs_in_parallel_and_awaits_approval(
    graph, redis_client, keys, fixture_world, cases, mcp_server_url
):
    """Orchestrator -> two investigator workers in parallel -> fan-in -> verifier."""
    record = record_of(fixture_world, "peeling_chain")
    case = await cases(record)
    settings = load_settings()
    events, queue = EventStream(redis_client, keys), JobQueue(redis_client, keys)
    fanin, store = FanIn(redis_client, keys), CaseStore(graph)
    await queue.enqueue(Job.new("investigate", case["id"], {"alert_id": record.alert_id}))

    async def choose(case_, summary):
        return ["peeling_chain", "fan_out", "round_trip"]

    async def summarise(case_):
        return await orchestrator_worker.structural_summary(graph, case_)

    orchestrator = Consumer(redis_client, keys, "investigate", "orchestrator", "orc", (
        orchestrator_worker.make_handler(store, fanin, queue, events, summarise, choose,
                                         deadline_s=120)))

    def investigator(name):
        async def run(brief, on_event):
            await asyncio.sleep(0.2)  # long enough for the other worker to take a job
            return await investigate(
                AgentRuntime(settings, mcp_url=mcp_server_url), brief, on_event=on_event,
                model=scripted(brief.seed_account_id, brief.hypothesis, []))
        handler = investigator_handler(run, events, queue, fanin=fanin,
                                       save_findings=store.save_findings, worker=name)
        return Consumer(redis_client, keys, "hypothesis", "investigator", name, handler)

    workers = [investigator("inv-1"), investigator("inv-2")]
    verifier = Consumer(redis_client, keys, "verify", "verifier", "ver",
                        verifier_worker.make_handler(graph, events, settings))

    await orchestrator.run_once(block_ms=100)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        await asyncio.gather(*(w.run_once(block_ms=50) for w in workers))
        if await verifier.run_once(block_ms=50):
            break

    final = await store.get(case["id"])
    assert final["status"] == "awaiting_approval"
    started = [e.data for e in await events.read_all(case["id"])
               if e.type == "investigation_started"]
    assert sorted(e["hypothesis"] for e in started) == ["fan_out", "peeling_chain", "round_trip"]
    assert {e["worker"] for e in started} == {"inv-1", "inv-2"}
