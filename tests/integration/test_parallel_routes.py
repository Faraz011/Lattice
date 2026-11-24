"""Two routes out of one account are both returned by the chain tool, so both get cited."""

import random

import pytest

from lattice.datagen import typologies
from lattice.datagen.background import build_background
from lattice.datagen.builder import WINDOW_START, WorldBuilder, days
from lattice.graph.loader import load_batch
from lattice.graph.schema import apply_schema
from lattice.graph.subgraph import load_evidence
from lattice.mcp_server import tools_graph
from lattice.scoring.scorer import Scorer

# A seed far from every generated world's, so this world's IDs collide with none of them.
SEED = 917_331


@pytest.fixture
async def world(graph):
    b = WorldBuilder(SEED)
    build_background(b, random.Random(SEED), persons=20, businesses=3)
    pattern = typologies.parallel_mules(b, random.Random(SEED), WINDOW_START + days(30))
    await apply_schema(graph)
    await load_batch(graph, b.batch)
    yield pattern
    await graph.write("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=b.batch.node_ids())


@pytest.mark.parametrize("ratio", [0.8, 0.95])
async def test_the_chain_tool_returns_both_parallel_routes(graph, world, ratio):
    result = await tools_graph.match_pattern(graph, "chain", world.seed_account_id,
                                             min_forward_ratio=ratio)

    cited = set(result.rel_ids)
    assert all(set(route) <= cited for route in world.routes)
    # Maximal paths only: no match is a prefix of another.
    edge_sets = [set(m.rel_ids) - set(m.context_rel_ids) for m in result.matches]
    assert not any(a < b for a in edge_sets for b in edge_sets)


async def test_cited_routes_score_as_redundant_evidence(graph, world):
    result = await tools_graph.match_pattern(graph, "chain", world.seed_account_id)
    evidence = await load_evidence(graph, result.rel_ids)

    score = Scorer().score(evidence)
    without_first = Scorer().score(evidence.without(set(world.routes[0])))

    assert score.score >= 0.6 and without_first.score >= 0.6
