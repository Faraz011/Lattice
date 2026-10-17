"""An Elliptic2 slice in Neo4j: structural tools work on flows with no amounts or times."""

import uuid
from pathlib import Path

import pytest

from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema
from lattice.graph.subgraph import load_evidence
from lattice.ingest.elliptic2 import account_id, build_slice, transfer_id
from lattice.mcp_server import tools_algo, tools_graph
from lattice.scoring.scorer import Scorer
from lattice.workers.orchestrator_worker import structural_summary

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "elliptic2_sample"
SLICE = build_slice(SAMPLE, subgraphs=10, neighbors=3, seed=2)
CYCLE = [transfer_id("1", "2"), transfer_id("2", "3"), transfer_id("3", "1")]


@pytest.fixture
async def loaded(graph):
    await apply_schema(graph)
    await load_batch(graph, SLICE.batch)
    yield SLICE
    await graph.write("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=SLICE.batch.node_ids())


async def test_loading_twice_changes_nothing(graph, loaded):
    await load_batch(graph, SLICE.batch)

    rows = await graph.read(
        "MATCH (a:Account)-[t:TRANSFER]->() WHERE a.id STARTS WITH 'acct_ell' "
        "RETURN count(t) AS flows, count(t.amount) AS priced")
    assert rows[0]["flows"] == len(SLICE.batch.transfers)
    assert rows[0]["priced"] == 0  # no amounts were stored


async def test_neighbours_and_paths_work_without_amounts_or_times(graph, loaded):
    around = await tools_graph.neighbors(graph, account_id("1"))
    paths = await tools_graph.find_paths(graph, account_id("1"), account_id("3"))

    assert transfer_id("1", "100") in around.rel_ids
    assert paths.paths and paths.paths[0].rel_ids == [transfer_id("1", "2"),
                                                      transfer_id("2", "3")]


async def test_a_cycle_is_found_structurally(graph, loaded):
    result = await tools_graph.match_pattern(graph, "cycle", account_id("1"))

    assert any(set(m.rel_ids) == set(CYCLE) for m in result.matches)
    assert all(m.total_amount == 0.0 and m.span_hours == 0.0 for m in result.matches)


async def test_a_fan_out_counts_counterparties_without_a_time_window(graph, loaded):
    result = await tools_graph.match_pattern(graph, "fan_out", account_id("4"), min_count=3)

    (match,) = result.matches
    assert match.counterparties == 4  # 5, and three background neighbours
    assert match.span_hours == 0.0


async def test_graph_algorithms_run_on_the_slice(graph, loaded):
    rank = await tools_algo.pagerank(graph, account_id("1"), hops=2)
    community = await tools_algo.communities(graph, account_id("6"), algorithm="wcc")
    impact = await tools_algo.impact(graph, account_id("6"), hops=2)

    assert rank.node_ids
    assert account_id("6") in community.node_ids
    assert impact.account_count >= 3


async def test_cited_flows_load_as_evidence_and_score_zero_without_failing(graph, loaded):
    evidence = await load_evidence(graph, CYCLE)

    assert {t.id for t in evidence.transfers()} == set(CYCLE)
    assert all(t.ts is None and t.amount is None for t in evidence.transfers())
    assert Scorer().score(evidence).score == 0.0


async def test_the_orchestrator_summary_reads_a_cluster(graph, loaded):
    case_id = f"case_e2{uuid.uuid4().hex[:10]}"
    try:
        summary = await structural_summary(graph, {"id": case_id,
                                                   "seed_account_id": account_id("1")})
    finally:
        await graph.write("MATCH (l:LedgerEntry {case_id: $c}) DELETE l", c=case_id)

    assert "amounts unknown" in summary
    assert "cluster" in summary
