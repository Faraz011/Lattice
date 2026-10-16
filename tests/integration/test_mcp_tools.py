"""Tool behaviour against the fixture world in Neo4j (`docker compose up -d neo4j redis`)."""

import asyncio
import json
import uuid
from collections import defaultdict

import pytest

from lattice.datagen.injection import INJECTION_MEMOS
from lattice.mcp_server import tools_algo, tools_case, tools_graph
from lattice.mcp_server.ledger import MissingCaseContext, ToolContext, run_tool
from lattice.mcp_server.tools_algo import projection


@pytest.fixture
async def ctx(graph, fixture_world):
    case_id = f"case_test{uuid.uuid4().hex[:12]}"
    yield ToolContext(graph=graph, case_id=case_id)
    await graph.write(
        "MATCH (n) WHERE (n:LedgerEntry OR n:Action) AND n.case_id = $c DETACH DELETE n",
        c=case_id,
    )


def case_of(world, kind, category="planted"):
    return next(c for c in world.manifest.cases
                if c.kind == kind and c.category == category and not c.case_id.endswith("twin"))


def forward_chain(world, case):
    """The peeling chain's forwarding transfers, origin first."""
    transfers = {t.id: t for t in world.batch.transfers if t.id in set(case.transfer_ids)}
    out = defaultdict(list)
    for t in transfers.values():
        out[t.src].append(t)
    chain, here = [], case.seed_account_id
    while out[here]:
        biggest = max(out[here], key=lambda t: t.amount)
        chain.append(biggest)
        here = biggest.dst
    return chain


async def ledger_entries(graph, case_id):
    return await graph.read(
        "MATCH (l:LedgerEntry {case_id: $c}) RETURN l ORDER BY l.ts", c=case_id
    )


async def projections(graph):
    rows = await graph.read("CALL gds.graph.list() YIELD graphName RETURN graphName")
    return [r["graphName"] for r in rows if r["graphName"].startswith("lattice-")]


# --- paths, neighbours, envelope ---------------------------------------------------------


async def test_find_paths_follows_a_planted_peeling_chain(ctx, fixture_world):
    case = case_of(fixture_world, "peeling_chain")
    chain = forward_chain(fixture_world, case)

    result = await tools_graph.find_paths(ctx.graph, chain[0].src, chain[-1].dst, max_hops=8)

    assert result.paths, "expected at least one path"
    assert result.paths[0].rel_ids == [t.id for t in chain]
    assert set(result.rel_ids) >= {t.id for t in chain}


async def test_neighbors_respects_direction_and_time_window(ctx, fixture_world):
    case = case_of(fixture_world, "fan_in_structuring")
    collector = case.seed_account_id
    deposits = [t for t in fixture_world.batch.transfers
                if t.dst == collector and t.id in set(case.transfer_ids)]
    earliest = min(t.ts for t in deposits)

    inbound = await tools_graph.neighbors(ctx.graph, collector, direction="in",
                                          rel_types=["TRANSFER"])
    windowed = await tools_graph.neighbors(ctx.graph, collector, direction="in",
                                           rel_types=["TRANSFER"], until=earliest)

    assert {t.id for t in deposits} <= set(inbound.rel_ids)
    assert all(r.dst == collector for r in inbound.rels)
    assert len(windowed.rels) < len(inbound.rels)
    assert all(r.props["ts"] <= earliest.isoformat() for r in windowed.rels)


async def test_injected_memo_comes_back_only_inside_the_envelope(ctx, fixture_world):
    case = next(c for c in fixture_world.manifest.cases if c.injected_transfer_id)
    transfer = next(t for t in fixture_world.batch.transfers if t.id == case.injected_transfer_id)

    result = await tools_graph.neighbors(ctx.graph, transfer.src, direction="out",
                                         rel_types=["TRANSFER"])
    rel = next(r for r in result.rels if r.id == transfer.id)

    assert "memo" not in rel.props
    assert rel.text["memo"].content in INJECTION_MEMOS
    payload = json.loads(result.model_dump_json())
    rel_json = next(r for r in payload["rels"] if r["id"] == transfer.id)
    assert transfer.memo not in json.dumps(rel_json["props"])


async def test_get_node_quarantines_customer_names(ctx, fixture_world):
    customer = fixture_world.batch.customers[0]

    result = await tools_graph.get_node(ctx.graph, customer.id)

    assert result.node.id == customer.id
    assert "name" not in result.node.props
    assert result.node.text["name"].content == customer.name
    assert result.node_ids == [customer.id]


async def test_get_node_reports_an_unknown_id_as_not_found(ctx):
    with pytest.raises(tools_graph.NotFound):
        await tools_graph.get_node(ctx.graph, "acct_doesnotexist0000")


async def test_match_pattern_finds_structuring_deposits(ctx, fixture_world):
    case = case_of(fixture_world, "fan_in_structuring")

    result = await tools_graph.match_pattern(
        ctx.graph, "fan_in", case.seed_account_id, window_days=7, min_count=10,
        min_amount=8_000, max_amount=9_999.99,
    )

    assert result.matches
    deposits = {t for t in case.transfer_ids} & set(result.matches[0].rel_ids)
    assert len(deposits) >= 10


async def test_a_chain_match_carries_the_opening_deposit_and_the_skims(ctx, fixture_world):
    case = case_of(fixture_world, "peeling_chain")
    transfers = {t.id: t for t in fixture_world.batch.transfers}
    deposit = next(transfers[t] for t in case.transfer_ids
                   if transfers[t].dst == case.seed_account_id)
    forwards = {t.id for t in forward_chain(fixture_world, case)}
    skims = set(case.transfer_ids) - forwards - {deposit.id}

    result = await tools_graph.match_pattern(ctx.graph, "chain", case.seed_account_id)

    best = result.matches[0]
    assert deposit.id in best.context_rel_ids
    assert skims <= set(best.context_rel_ids)
    assert set(case.transfer_ids) <= set(best.rel_ids)


async def test_a_fan_out_match_carries_the_funding_deposit(ctx, fixture_world):
    case = case_of(fixture_world, "fan_out")
    deposit = next(t for t in fixture_world.batch.transfers
                   if t.dst == case.seed_account_id and t.id in set(case.transfer_ids))

    result = await tools_graph.match_pattern(ctx.graph, "fan_out", case.seed_account_id,
                                             min_count=8)

    assert result.matches[0].context_rel_ids == [deposit.id]
    assert set(case.transfer_ids) <= set(result.rel_ids)


async def test_match_pattern_finds_a_round_trip_cycle(ctx, fixture_world):
    case = case_of(fixture_world, "round_trip")

    result = await tools_graph.match_pattern(ctx.graph, "cycle", case.seed_account_id,
                                             max_length=6)

    assert any(set(m.rel_ids) == set(case.transfer_ids) for m in result.matches)


# --- guarded cypher -----------------------------------------------------------------------


async def test_cypher_readonly_caps_rows_and_flags_truncation(ctx):
    result = await tools_graph.cypher_readonly(
        ctx.graph, "MATCH ()-[t:TRANSFER]->() RETURN t.id AS id LIMIT 500", row_cap=50
    )

    assert len(result.rows) == 50
    assert result.truncated is True
    assert len(result.rel_ids) == 50


async def test_cypher_readonly_rejects_a_write_before_running_it(ctx):
    marker = f"acct_guard{uuid.uuid4().hex[:8]}"
    with pytest.raises(tools_graph.CypherRejected):
        await tools_graph.cypher_readonly(ctx.graph, f"CREATE (:Account {{id: '{marker}'}})")

    rows = await ctx.graph.read("MATCH (a:Account {id: $id}) RETURN a", id=marker)
    assert rows == []


async def test_cypher_readonly_extracts_ids_from_nodes_and_strings(ctx, fixture_world):
    account = fixture_world.batch.accounts[0]

    result = await tools_graph.cypher_readonly(
        ctx.graph, "MATCH (a:Account {id: $id}) RETURN a, a.id AS id", params={"id": account.id}
    )

    assert result.node_ids == [account.id]


# --- ledger and case context --------------------------------------------------------------


async def test_every_tool_call_writes_one_matching_ledger_entry(ctx, fixture_world):
    seed = case_of(fixture_world, "fan_out").seed_account_id

    result = await run_tool(ctx, "graph_neighbors", {"node_id": seed},
                            lambda: tools_graph.neighbors(ctx.graph, seed))

    entries = await ledger_entries(ctx.graph, ctx.case_id)
    assert len(entries) == 1
    entry = entries[0]["l"]
    assert entry["result_id"] == result.result_id
    assert entry["tool"] == "graph_neighbors"
    assert json.loads(entry["params"]) == {"node_id": seed}
    assert sorted(entry["rel_ids"]) == sorted(result.rel_ids)
    assert sorted(entry["node_ids"]) == sorted(result.node_ids)


async def test_a_call_without_case_context_is_refused_and_not_ledgered(graph, fixture_world):
    seed = fixture_world.batch.accounts[0].id
    called = False

    async def call():
        nonlocal called
        called = True
        return await tools_graph.neighbors(graph, seed)

    with pytest.raises(MissingCaseContext):
        await run_tool(ToolContext(graph=graph, case_id=""), "graph_neighbors", {}, call)

    assert called is False
    rows = await graph.read("MATCH (l:LedgerEntry {case_id: ''}) RETURN count(l) AS n")
    assert rows[0]["n"] == 0


async def test_a_failing_tool_writes_no_ledger_entry(ctx):
    async def boom():
        raise RuntimeError("algorithm failed")

    with pytest.raises(RuntimeError):
        await run_tool(ctx, "algo_pagerank", {}, boom)

    assert await ledger_entries(ctx.graph, ctx.case_id) == []


# --- algorithms ---------------------------------------------------------------------------


async def test_communities_place_a_planted_ring_together(ctx, fixture_world):
    case = case_of(fixture_world, "round_trip")

    result = await tools_algo.communities(ctx.graph, case.seed_account_id)

    assert set(case.account_ids) <= set(result.members)
    assert await projections(ctx.graph) == []


async def test_pagerank_ranks_the_neighbourhood_and_cleans_up(ctx, fixture_world):
    case = case_of(fixture_world, "fan_in_structuring")

    result = await tools_algo.pagerank(ctx.graph, case.seed_account_id, top_k=5)

    assert len(result.ranked) == 5
    assert result.ranked[0].id == case.seed_account_id  # the collector is the hub
    assert await projections(ctx.graph) == []


async def test_concurrent_pagerank_calls_on_one_neighbourhood_both_succeed(ctx, fixture_world):
    seed = case_of(fixture_world, "fan_out").seed_account_id

    first, second = await asyncio.gather(
        tools_algo.pagerank(ctx.graph, seed), tools_algo.pagerank(ctx.graph, seed)
    )

    assert [r.id for r in first.ranked] == [r.id for r in second.ranked]
    assert await projections(ctx.graph) == []


async def test_a_projection_is_dropped_even_when_the_algorithm_fails(ctx, fixture_world):
    seed = case_of(fixture_world, "fan_out").seed_account_id

    with pytest.raises(RuntimeError):
        async with projection(ctx.graph, seed, hops=1) as name:
            assert name in await projections(ctx.graph)
            raise RuntimeError("algorithm failed mid-run")

    assert await projections(ctx.graph) == []


async def test_similar_finds_accounts_sharing_counterparties(ctx, fixture_world):
    case = case_of(fixture_world, "shared_device")
    senders = case.account_ids[:-1]  # all pay the same destination

    result = await tools_algo.similar(ctx.graph, senders[0])

    assert set(senders[1:]) <= {s.id for s in result.similar}
    assert await projections(ctx.graph) == []


async def test_impact_returns_reachable_accounts_and_their_customers(ctx, fixture_world):
    case = case_of(fixture_world, "fan_out")
    seed = case.seed_account_id
    adjacency = defaultdict(set)
    for t in fixture_world.batch.transfers:
        adjacency[t.src].add(t.dst)
        adjacency[t.dst].add(t.src)
    reachable = {seed} | adjacency[seed]
    reachable |= {n for a in adjacency[seed] for n in adjacency[a]}
    owners = {a.customer_id for a in fixture_world.batch.accounts if a.id in reachable}

    result = await tools_algo.impact(ctx.graph, seed, hops=2)

    assert set(result.accounts) == reachable
    assert set(result.customers) == owners
    assert result.account_count == len(reachable)
    assert await projections(ctx.graph) == []


# --- case tools ---------------------------------------------------------------------------


async def test_propose_action_creates_a_proposed_action_and_nothing_else(ctx, fixture_world):
    target = case_of(fixture_world, "peeling_chain").seed_account_id

    result = await tools_case.propose_action(
        ctx.graph, ctx.case_id, kind="freeze", target_id=target, rationale="peeling chain"
    )

    rows = await ctx.graph.read("MATCH (a:Action {id: $id}) RETURN a", id=result.action_id)
    action = rows[0]["a"]
    assert action["status"] == "proposed"
    assert action["tier"] == 3
    assert action["case_id"] == ctx.case_id
    assert action["target_id"] == target


async def test_cite_accepts_ledgered_ids_and_rejects_others(ctx, fixture_world):
    seed = case_of(fixture_world, "fan_out").seed_account_id
    looked_up = await run_tool(ctx, "graph_neighbors", {"node_id": seed},
                               lambda: tools_graph.neighbors(ctx.graph, seed))
    real = looked_up.rel_ids[0]

    citation = await tools_case.cite(
        ctx.graph, ctx.case_id, claim="hub pays many accounts",
        result_ids=[looked_up.result_id], rel_ids=[real, "tx_fabricated000000"],
    )

    assert citation.rel_ids == [real]
    assert citation.rejected_ids == ["tx_fabricated000000"]
