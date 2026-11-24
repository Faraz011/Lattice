"""The verifier against compose Neo4j and Redis, with real ledger entries from real tool calls."""

import uuid

import pytest
from test_investigator_flow import scripted

from lattice.agents.investigator import investigate
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Claim, Finding, HypothesisBrief
from lattice.cases.actions import ActionStore
from lattice.cases.store import CaseStore
from lattice.config import load_settings
from lattice.mcp_server import tools_graph
from lattice.mcp_server.ledger import ToolContext, run_tool
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.workers.investigator_worker import make_handler as investigator_handler
from lattice.workers.verifier_worker import make_handler


@pytest.fixture
async def cases(graph):
    created: list[str] = []

    async def start(record):
        case, _ = await CaseStore(graph).start(record.alert_id, "single", 10_000, 100_000)
        created.append(case["id"])
        return case

    yield start
    await graph.write(
        "MATCH (n) WHERE (n:Case AND n.id IN $ids) OR ((n:Action OR n:LedgerEntry OR n:Recording) "
        "AND n.case_id IN $ids) DETACH DELETE n", ids=created)


def record_of(world, kind, category="planted"):
    return next(c for c in world.manifest.cases
                if c.kind == kind and c.category == category and not c.case_id.endswith("twin"))


async def ledgered(graph, case_id, call, tool="graph_match_pattern", params=None):
    return await run_tool(ToolContext(graph=graph, case_id=case_id), tool, params or {}, call)


def finding_from(result, hypothesis, verdict="supports", extra_rel_ids=(), status="complete"):
    claim = Claim(statement="pattern", rel_ids=[*result.rel_ids, *extra_rel_ids],
                  result_ids=[result.result_id])
    if status != "complete":
        partial = Finding.partial(hypothesis, "rate budget exhausted", status)
        return partial.model_copy(update={"claims": [claim]})
    return Finding(hypothesis=hypothesis, verdict=verdict, confidence=0.8, summary="s",
                   claims=[claim])


async def verify(graph, redis_client, keys, case_id, findings):
    events = EventStream(redis_client, keys)
    job = Job.new("verify", case_id, {"findings": [f.model_dump(mode="json") for f in findings]})
    await make_handler(graph, events, load_settings())(job)
    case = await CaseStore(graph).get(case_id)
    verdicts = [e.data for e in await events.read_all(case_id) if e.type == "verdict"]
    return case, verdicts[-1] if verdicts else None


async def chain_finding(graph, fixture_world, case, **kwargs):
    seed = case["seed_account_id"]
    result = await ledgered(graph, case["id"],
                            lambda: tools_graph.match_pattern(graph, "chain", seed))
    return finding_from(result, "peeling_chain", **kwargs)


async def test_agreement_on_a_planted_chain_awaits_approval_with_a_blast_radius(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    finding = await chain_finding(graph, fixture_world, case)

    updated, verdict = await verify(graph, redis_client, keys, case["id"], [finding])

    assert updated["status"] == "awaiting_approval"
    assert verdict["verdict"]["suspicious"] and verdict["verdict"]["typology"] == "peeling_chain"
    (action,) = await ActionStore(graph).for_case(case["id"])
    assert action["tier"] >= 2 and action["status"] == "proposed"
    assert action["target_id"] == case["seed_account_id"]
    assert action["blast_radius"]["account_count"] > 0
    circuit = verdict["circuit"]["circuit"]
    cited = {r for c in verdict["verdict"]["claims"] for r in c["rel_ids"]}
    assert circuit["status"] == "circuit"
    assert circuit["circuit_edges"] and set(circuit["circuit_edges"]) <= cited
    assert circuit["sufficiency_score"] >= load_settings().risk_threshold
    assert verdict["narrative"]["source"] == "template"
    assert circuit["typology"] in verdict["narrative"]["text"]
    stored = await CaseStore(graph).get(case["id"])
    assert stored["circuit"] and stored["narrative"]


async def test_a_fabricated_citation_is_dropped_and_listed(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    honest = await chain_finding(graph, fixture_world, case)
    forged = Finding(hypothesis="peeling_chain", verdict="supports", confidence=0.9,
                     summary="s", claims=[*honest.claims, Claim(
                         statement="invented", rel_ids=["tx_forged0000000000"],
                         result_ids=honest.claims[0].result_ids)])

    _, verdict = await verify(graph, redis_client, keys, case["id"], [forged])

    assert verdict["verdict"]["rejected_citations"] == ["tx_forged0000000000"]
    cited = {r for c in verdict["verdict"]["claims"] for r in c["rel_ids"]}
    assert "tx_forged0000000000" not in cited


async def test_a_cited_transfer_deleted_after_citation_fails_reverification(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    a, b = fixture_world.batch.accounts[0].id, fixture_world.batch.accounts[1].id
    temp_id = f"tx_temp{uuid.uuid4().hex[:12]}"
    await graph.write(
        "MATCH (a:Account {id: $a}), (b:Account {id: $b}) "
        "CREATE (a)-[:TRANSFER {id: $id, amount: 1.0, ts: datetime(), channel: 'wire'}]->(b)",
        a=a, b=b, id=temp_id)
    looked_up = await ledgered(graph, case["id"],
                               lambda: tools_graph.neighbors(graph, a, direction="out"),
                               tool="graph_neighbors")
    assert temp_id in looked_up.rel_ids
    await graph.write("MATCH ()-[t:TRANSFER {id: $id}]->() DELETE t", id=temp_id)
    finding = Finding(hypothesis="fan_out", verdict="refutes", confidence=0.5, summary="s",
                      claims=[Claim(statement="temp", rel_ids=[temp_id],
                                    result_ids=[looked_up.result_id])])

    _, verdict = await verify(graph, redis_client, keys, case["id"], [finding])

    assert verdict["verdict"]["unverified_ids"] == [temp_id]
    assert verdict["verdict"]["claims"] == []


async def test_a_decoy_the_investigators_wrongly_support_goes_to_review(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "payroll_fan_out", category="decoy"))
    seed = case["seed_account_id"]
    result = await ledgered(graph, case["id"],
                            lambda: tools_graph.neighbors(graph, seed, direction="out",
                                                          rel_types=["TRANSFER"]),
                            tool="graph_neighbors")

    updated, verdict = await verify(graph, redis_client, keys, case["id"],
                                    [finding_from(result, "fan_out", "supports")])

    assert updated["status"] == "needs_review"
    assert "disagree" in updated["status_reason"]
    assert await ActionStore(graph).for_case(case["id"]) == []
    # A flagged verdict still reports its circuit, honestly: below the threshold, none drawn.
    assert verdict["circuit"]["circuit"]["status"] == "below_threshold"


async def test_a_refuted_decoy_closes_with_its_score_as_the_reason(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "payroll_fan_out", category="decoy"))
    seed = case["seed_account_id"]
    result = await ledgered(graph, case["id"],
                            lambda: tools_graph.neighbors(graph, seed, direction="out",
                                                          rel_types=["TRANSFER"]),
                            tool="graph_neighbors")

    updated, _ = await verify(graph, redis_client, keys, case["id"],
                              [finding_from(result, "fan_out", "refutes")])

    assert updated["status"] == "closed_no_action"
    assert "below the 0.60 threshold" in updated["status_reason"]
    recorded = await graph.read("MATCH (r:Recording {case_id: $c}) RETURN r.event_count AS n",
                                c=case["id"])
    assert recorded and recorded[0]["n"] >= 2  # every verdict is saved for replay


async def test_a_partial_finding_still_contributes_its_citations(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    partial = await chain_finding(graph, fixture_world, case, status="partial")

    updated, verdict = await verify(graph, redis_client, keys, case["id"], [partial])

    assert verdict["score"]["score"] >= load_settings().risk_threshold
    assert any("partial" in note for note in verdict["verdict"]["notes"])
    assert updated["status"] == "needs_review"


async def test_verifying_the_same_case_twice_does_not_propose_twice(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    finding = await chain_finding(graph, fixture_world, case)

    await verify(graph, redis_client, keys, case["id"], [finding])
    await verify(graph, redis_client, keys, case["id"], [finding])

    assert len(await ActionStore(graph).for_case(case["id"])) == 1


async def test_a_verify_job_redelivered_mid_way_reuses_the_open_proposal(
    graph, redis_client, keys, fixture_world, cases
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    finding = await chain_finding(graph, fixture_world, case)
    await verify(graph, redis_client, keys, case["id"], [finding])
    # The worker died after proposing but before the case left `verifying`.
    await graph.write("MATCH (c:Case {id: $id}) SET c.status = 'verifying'", id=case["id"])

    updated, _ = await verify(graph, redis_client, keys, case["id"], [finding])

    assert updated["status"] == "awaiting_approval"
    (action,) = await ActionStore(graph).for_case(case["id"])
    assert action["status"] == "proposed" and action["blast_radius"]


async def test_single_agent_path_from_alert_to_awaiting_approval(
    graph, redis_client, keys, fixture_world, cases, mcp_server_url
):
    """Investigator (scripted model, real MCP) hands a finding to the verifier, end to end."""
    record = record_of(fixture_world, "fan_out")
    case = await cases(record)
    verify_jobs: list[Job] = []

    class Queue:
        async def enqueue(self, job):
            verify_jobs.append(job)

    async def run_investigation(brief, on_event):
        return await investigate(AgentRuntime(load_settings(), mcp_url=mcp_server_url), brief,
                                 on_event=on_event,
                                 model=scripted(brief.seed_account_id, "fan_out", []))

    events = EventStream(redis_client, keys)
    brief = HypothesisBrief(case_id=case["id"], alert_id=record.alert_id,
                            seed_account_id=record.seed_account_id, alert_reason="r",
                            hypothesis="open")
    await investigator_handler(run_investigation, events, Queue())(Job.new(
        "hypothesis", case["id"], {"brief": brief.model_dump(), "single_agent": True}))
    (verify_job,) = verify_jobs
    await make_handler(graph, events, load_settings())(verify_job)

    updated = await CaseStore(graph).get(case["id"])
    assert updated["status"] == "awaiting_approval"
    verdict = next(e.data for e in await events.read_all(case["id"]) if e.type == "verdict")
    ledger = await graph.read("MATCH (l:LedgerEntry {case_id: $c}) RETURN l.rel_ids AS r",
                              c=case["id"])
    ledgered_ids = {r for row in ledger for r in row["r"]}
    cited = {r for c in verdict["verdict"]["claims"] for r in c["rel_ids"]}
    assert cited and cited <= ledgered_ids
