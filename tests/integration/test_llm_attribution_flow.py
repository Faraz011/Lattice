"""LLM attribution on a real case: the verifier attaches it for tier 2-3 proposals only."""

import json

import pytest
from test_verifier import cases, chain_finding, finding_from, ledgered, record_of  # noqa: F401

from lattice.agents.runtime import AgentRuntime
from lattice.cases.store import CaseStore
from lattice.config import load_settings
from lattice.explain.llm_attribution import attribute_case
from lattice.mcp_server import tools_graph
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.workers.verifier_worker import make_handler

SAMPLES = 12


@pytest.fixture
def attribute(graph):
    settings = load_settings().model_copy(update={"model": "scripted", "role_models": {}})
    runtime = AgentRuntime(settings, mcp_url=None)

    async def run(case, cited, report):
        return await attribute_case(graph, runtime, case, cited, report.circuit.circuit_edges,
                                    samples=SAMPLES, max_sources=8)

    return run


async def verify(graph, redis_client, keys, case_id, findings, attribute):
    job = Job.new("verify", case_id, {"findings": [f.model_dump(mode="json") for f in findings]})
    await make_handler(graph, EventStream(redis_client, keys), load_settings(),
                       attribute=attribute)(job)
    return await CaseStore(graph).get(case_id)


async def test_a_flagged_case_reports_what_the_judgement_leaned_on(
    graph, redis_client, keys, fixture_world, cases, attribute  # noqa: F811
):
    case = await cases(record_of(fixture_world, "peeling_chain"))
    seed = case["seed_account_id"]
    # A second, irrelevant tool result the judge also sees.
    noise = await ledgered(graph, case["id"], lambda: tools_graph.get_node(graph, seed),
                           tool="graph_get_node")
    finding = await chain_finding(graph, fixture_world, case)
    finding.claims.append(finding.claims[0].model_copy(update={
        "statement": "seed record", "rel_ids": [], "node_ids": [seed],
        "result_ids": [noise.result_id]}))

    stored = await verify(graph, redis_client, keys, case["id"], [finding], attribute)

    assert stored["status"] == "awaiting_approval"
    attribution = json.loads(stored["circuit"])["llm_attribution"]
    assert attribution["status"] == "complete"
    assert attribution["samples"] == SAMPLES
    top = attribution["sources"][0]
    assert top["tool"] == "graph_match_pattern"
    assert top["circuit_edges"]  # the judgement leans where the scorer's proof is
    assert attribution["agreement"] == 1.0
    assert attribution["full_probability"] == 0.85


async def test_a_closed_case_spends_nothing_on_attribution(
    graph, redis_client, keys, fixture_world, cases  # noqa: F811
):
    case = await cases(record_of(fixture_world, "payroll_fan_out", category="decoy"))
    seed = case["seed_account_id"]
    result = await ledgered(graph, case["id"],
                            lambda: tools_graph.neighbors(graph, seed, direction="out"),
                            tool="graph_neighbors")
    calls = 0

    async def counting(*args):
        nonlocal calls
        calls += 1

    stored = await verify(graph, redis_client, keys, case["id"],
                          [finding_from(result, "fan_out", "refutes")], counting)

    assert stored["status"] == "closed_no_action"
    assert calls == 0
