"""Graph algorithm tools (R6) on bounded, per-call GDS projections of the transfer graph.

Each call projects only the accounts near the focus node, under a unique name, and drops the
projection in a `finally` path, so concurrent investigators never share or leak projections.
Only `Account` nodes and `TRANSFER` relationships are projected (never app labels, KTD5).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from pydantic import BaseModel

from lattice.graph.client import GraphClient
from lattice.mcp_server.ledger import ToolResult
from lattice.mcp_server.tools_graph import NotFound, label_for

MAX_PROJECTION_NODES = 2_000
MAX_LISTED = 500


async def _require_account(graph: GraphClient, node_id: str) -> None:
    if label_for(node_id) != "Account":
        raise ValueError("graph algorithms run around an account")
    rows = await graph.read("MATCH (a:Account {id: $id}) RETURN count(a) AS n", id=node_id)
    if rows[0]["n"] == 0:
        raise NotFound(f"no Account with id {node_id}")


@asynccontextmanager
async def projection(
    graph: GraphClient, node_id: str, hops: int = 2, undirected: bool = True
) -> AsyncIterator[str]:
    """Project the accounts within `hops` transfers of the focus account; always drop it."""
    await _require_account(graph, node_id)
    name = f"lattice-{uuid.uuid4().hex}"
    hops = max(1, min(hops, 3))
    config = "{undirectedRelationshipTypes: ['*']}" if undirected else "{}"
    try:
        await graph.write(
            f"""
            MATCH (focus:Account {{id: $id}})
            CALL (focus) {{
              MATCH (focus)-[:TRANSFER*0..{hops}]-(n:Account)
              RETURN DISTINCT n LIMIT $max
            }}
            WITH collect(n) AS nodes
            UNWIND nodes AS a
            OPTIONAL MATCH (a)-[t:TRANSFER]->(b:Account) WHERE b IN nodes
            WITH gds.graph.project($name, a, b,
                   {{relationshipProperties: {{amount: coalesce(t.amount, 0.0)}}}}, {config}) AS g
            RETURN g.nodeCount AS nodes
            """,
            id=node_id,
            name=name,
            max=MAX_PROJECTION_NODES,
        )
        yield name
    finally:
        await graph.write("CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                          name=name)


# --- algo_pagerank ------------------------------------------------------------------------


class Ranked(BaseModel):
    id: str
    score: float


class PageRankResult(ToolResult):
    ranked: list[Ranked]


async def pagerank(
    graph: GraphClient, node_id: str, hops: int = 2, top_k: int = 10
) -> PageRankResult:
    """Personalised PageRank from the focus account over its neighbourhood: who is central."""
    async with projection(graph, node_id, hops) as name:
        rows = await graph.read(
            """
            MATCH (focus:Account {id: $id})
            CALL gds.pageRank.stream($name, {sourceNodes: [focus]})
            YIELD nodeId, score
            RETURN gds.util.asNode(nodeId).id AS id, score
            ORDER BY score DESC, id LIMIT $k
            """,
            id=node_id,
            name=name,
            k=max(1, min(top_k, 50)),
        )
    ranked = [Ranked(id=r["id"], score=round(r["score"], 6)) for r in rows]
    return PageRankResult(ranked=ranked, node_ids=[r.id for r in ranked])


# --- algo_communities ---------------------------------------------------------------------


class CommunityResult(ToolResult):
    algorithm: str
    size: int
    members: list[str]
    truncated: bool = False


async def communities(
    graph: GraphClient,
    node_id: str,
    hops: int = 2,
    algorithm: Literal["louvain", "wcc"] = "louvain",
) -> CommunityResult:
    """The community the focus account belongs to within its neighbourhood."""
    procedure = {"louvain": "gds.louvain.stream", "wcc": "gds.wcc.stream"}[algorithm]
    column = "communityId" if algorithm == "louvain" else "componentId"
    async with projection(graph, node_id, hops) as name:
        rows = await graph.read(
            f"""
            CALL {procedure}($name) YIELD nodeId, {column} AS community
            WITH gds.util.asNode(nodeId).id AS id, community
            WITH collect({{id: id, community: community}}) AS all
            WITH all, [x IN all WHERE x.id = $id][0].community AS mine
            RETURN [x IN all WHERE x.community = mine | x.id] AS members
            """,
            name=name,
            id=node_id,
        )
    members = sorted(rows[0]["members"])
    listed = members[:MAX_LISTED]
    return CommunityResult(
        algorithm=algorithm,
        size=len(members),
        members=listed,
        truncated=len(members) > len(listed),
        node_ids=listed,
    )


# --- algo_similar -------------------------------------------------------------------------


class Similar(BaseModel):
    id: str
    similarity: float


class SimilarResult(ToolResult):
    similar: list[Similar]


async def similar(
    graph: GraphClient, node_id: str, hops: int = 2, top_k: int = 10
) -> SimilarResult:
    """Accounts that send to the same counterparties as the focus account (Jaccard)."""
    async with projection(graph, node_id, hops, undirected=False) as name:
        rows = await graph.read(
            """
            CALL gds.nodeSimilarity.stream($name, {topK: $k, similarityCutoff: 0.1})
            YIELD node1, node2, similarity
            WITH gds.util.asNode(node1).id AS a, gds.util.asNode(node2).id AS b, similarity
            WHERE a = $id
            RETURN b AS id, similarity ORDER BY similarity DESC, id
            """,
            name=name,
            id=node_id,
            k=max(1, min(top_k, 50)),
        )
    found = [Similar(id=r["id"], similarity=round(r["similarity"], 4)) for r in rows]
    return SimilarResult(similar=found, node_ids=[node_id, *(s.id for s in found)])


# --- algo_impact --------------------------------------------------------------------------


class ImpactResult(ToolResult):
    account_count: int
    customer_count: int
    accounts: list[str]
    customers: list[str]
    truncated: bool = False


async def impact(graph: GraphClient, node_id: str, hops: int = 2) -> ImpactResult:
    """Blast radius: accounts within `hops` transfers of the focus, and their customers."""
    await _require_account(graph, node_id)
    hops = max(1, min(hops, 3))
    rows = await graph.read(
        f"""
        MATCH (focus:Account {{id: $id}})
        CALL (focus) {{
          MATCH (focus)-[:TRANSFER*0..{hops}]-(a:Account)
          RETURN collect(DISTINCT a) AS accounts
        }}
        UNWIND accounts AS a
        OPTIONAL MATCH (c:Customer)-[:OWNS]->(a)
        RETURN collect(DISTINCT a.id) AS accounts, collect(DISTINCT c.id) AS customers
        """,
        id=node_id,
    )
    accounts, customers = sorted(rows[0]["accounts"]), sorted(rows[0]["customers"])
    listed_accounts, listed_customers = accounts[:MAX_LISTED], customers[:MAX_LISTED]
    return ImpactResult(
        account_count=len(accounts),
        customer_count=len(customers),
        accounts=listed_accounts,
        customers=listed_customers,
        truncated=len(accounts) > MAX_LISTED or len(customers) > MAX_LISTED,
        node_ids=listed_accounts + listed_customers,
    )
