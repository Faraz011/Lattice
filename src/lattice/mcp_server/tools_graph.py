"""Typed graph tools (R4, R6). Each returns IDs for every node and relationship it shows."""

from datetime import datetime, timedelta
from typing import Any, Literal

from neo4j.graph import Node, Path, Relationship
from pydantic import BaseModel

from lattice.graph.client import GraphClient
from lattice.graph.schema import DATA_LABELS, DATA_REL_TYPES, LABEL_BY_KIND, TRANSFER
from lattice.ids import kind_of
from lattice.mcp_server.cypher_guard import CypherRejected, check_plan, check_readonly
from lattice.mcp_server.envelope import UntrustedText
from lattice.mcp_server.ledger import ToolResult
from lattice.mcp_server.views import (
    NodeView,
    PathView,
    RelView,
    node_view,
    path_view,
    rel_view,
    unique,
)

__all__ = ["CypherRejected", "NotFound"]

MAX_HOPS = 3
MAX_PATH_HOPS = 8
MAX_LIMIT = 500


class NotFound(LookupError):
    """No data node has this ID."""


def label_for(node_id: str) -> str:
    try:
        return LABEL_BY_KIND[kind_of(node_id)]
    except (ValueError, KeyError):
        raise NotFound(
            f"{node_id!r} is not the ID of a customer, account, device or alert"
        ) from None


def _rel_pattern(rel_types: list[str] | None) -> str:
    types = rel_types or list(DATA_REL_TYPES)
    unknown = sorted(set(types) - set(DATA_REL_TYPES))
    if unknown:
        raise ValueError(f"unknown relationship type(s): {', '.join(unknown)}")
    return "|".join(types)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# --- graph_schema -------------------------------------------------------------------------


class SchemaResult(ToolResult):
    labels: list[str]
    relationship_types: list[str]
    properties: dict[str, list[str]]
    counts: dict[str, int]


async def graph_schema(graph: GraphClient) -> SchemaResult:
    properties: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for label in DATA_LABELS:
        rows = await graph.read(
            f"MATCH (n:{label}) WITH n LIMIT 200 UNWIND keys(n) AS k "
            "RETURN collect(DISTINCT k) AS keys"
        )
        properties[label] = sorted(rows[0]["keys"])
        counts[label] = (await graph.read(f"MATCH (n:{label}) RETURN count(n) AS n"))[0]["n"]
    for rel_type in DATA_REL_TYPES:
        rows = await graph.read(
            f"MATCH ()-[r:{rel_type}]->() WITH r LIMIT 200 UNWIND keys(r) AS k "
            "RETURN collect(DISTINCT k) AS keys"
        )
        properties[rel_type] = sorted(rows[0]["keys"])
        counts[rel_type] = (
            await graph.read(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS n")
        )[0]["n"]
    return SchemaResult(
        labels=list(DATA_LABELS),
        relationship_types=list(DATA_REL_TYPES),
        properties=properties,
        counts=counts,
    )


# --- graph_get_node -----------------------------------------------------------------------


class NodeResult(ToolResult):
    node: NodeView


async def get_node(graph: GraphClient, node_id: str) -> NodeResult:
    label = label_for(node_id)
    records, _ = await graph.read_records(
        f"MATCH (n:{label} {{id: $id}}) RETURN n", {"id": node_id}, timeout=10, max_rows=1
    )
    if not records:
        raise NotFound(f"no {label} with id {node_id}")
    return NodeResult(node=node_view(records[0]["n"]), node_ids=[node_id])


# --- graph_neighbors ----------------------------------------------------------------------


class SubgraphResult(ToolResult):
    nodes: list[NodeView]
    rels: list[RelView]
    truncated: bool = False


async def neighbors(
    graph: GraphClient,
    node_id: str,
    direction: Literal["in", "out", "both"] = "both",
    rel_types: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    hops: int = 1,
    limit: int = 200,
) -> SubgraphResult:
    label = label_for(node_id)
    types = _rel_pattern(rel_types)
    hops = _clamp(hops, 1, MAX_HOPS)
    limit = _clamp(limit, 1, MAX_LIMIT)
    arrow = {
        "out": f"-[rels:{types}*1..{hops}]->",
        "in": f"<-[rels:{types}*1..{hops}]-",
        "both": f"-[rels:{types}*1..{hops}]-",
    }[direction]
    records, truncated = await graph.read_records(
        f"""
        MATCH (start:{label} {{id: $id}})
        MATCH (start){arrow}(other)
        WHERE all(r IN rels WHERE type(r) <> '{TRANSFER}' OR (
                ($since IS NULL OR r.ts >= $since) AND ($until IS NULL OR r.ts <= $until)))
        WITH rels LIMIT 5000
        UNWIND rels AS r
        WITH DISTINCT r
        RETURN r, startNode(r) AS a, endNode(r) AS b
        """,
        {"id": node_id, "since": since, "until": until},
        timeout=15,
        max_rows=limit,
    )
    nodes: dict[str, NodeView] = {}
    rels: list[RelView] = []
    for record in records:
        a, b = record["a"], record["b"]
        nodes.setdefault(a["id"], node_view(a))
        nodes.setdefault(b["id"], node_view(b))
        rels.append(rel_view(record["r"], src=a["id"], dst=b["id"]))
    return SubgraphResult(
        nodes=list(nodes.values()),
        rels=rels,
        truncated=truncated,
        node_ids=list(nodes),
        rel_ids=[r.id for r in rels],
    )


# --- graph_find_paths ---------------------------------------------------------------------


class PathsResult(ToolResult):
    paths: list[PathView]


async def find_paths(
    graph: GraphClient,
    src_id: str,
    dst_id: str,
    max_hops: int = 6,
    k: int = 3,
    directed: bool = True,
    rel_types: list[str] | None = None,
) -> PathsResult:
    src_label, dst_label = label_for(src_id), label_for(dst_id)
    types = _rel_pattern(rel_types or [TRANSFER])
    max_hops = _clamp(max_hops, 1, MAX_PATH_HOPS)
    k = _clamp(k, 1, 10)
    arrow = f"-[:{types}]->" if directed else f"-[:{types}]-"
    records, _ = await graph.read_records(
        f"""
        MATCH (a:{src_label} {{id: $src}}), (b:{dst_label} {{id: $dst}})
        MATCH p = SHORTEST {k} (a){arrow}{{1,{max_hops}}}(b)
        RETURN p ORDER BY length(p)
        """,
        {"src": src_id, "dst": dst_id},
        timeout=15,
        max_rows=k,
    )
    paths = [path_view(record["p"]) for record in records]
    return PathsResult(
        paths=paths,
        node_ids=unique([n for p in paths for n in p.node_ids]),
        rel_ids=unique([r for p in paths for r in p.rel_ids]),
    )


# --- graph_match_pattern ------------------------------------------------------------------


class PatternMatch(BaseModel):
    node_ids: list[str]
    rel_ids: list[str]
    transfer_count: int
    counterparties: int
    total_amount: float
    span_hours: float
    # Edges around the core shape that make it what it is: the deposit that funds a fan-out
    # or a chain, the small skims at each chain hop, the onward transfer after a fan-in.
    # They are also in `rel_ids`, so citing a match cites the whole pattern.
    context_rel_ids: list[str] = []


class PatternResult(ToolResult):
    pattern: str
    matches: list[PatternMatch]


async def match_pattern(
    graph: GraphClient,
    pattern: Literal["fan_in", "fan_out", "cycle", "chain"],
    node_id: str,
    window_days: float = 7,
    min_count: int = 5,
    min_amount: float | None = None,
    max_amount: float | None = None,
    max_length: int = 6,
    max_gap_hours: float = 48,
    min_forward_ratio: float = 0.8,
    limit: int = 5,
) -> PatternResult:
    if label_for(node_id) != "Account":
        raise ValueError("patterns are matched from an account")
    if pattern in ("fan_in", "fan_out"):
        matches = await _fan(graph, pattern, node_id, window_days, min_count, min_amount,
                             max_amount)
    elif pattern == "cycle":
        matches = await _paths_as_matches(
            graph,
            f"MATCH p = (n:Account {{id: $id}})-[:{TRANSFER}*2..{_clamp(max_length, 2, 8)}]->(n) "
            "RETURN p LIMIT $limit",
            {"id": node_id, "limit": _clamp(limit, 1, 20)},
        )
    else:
        matches = await _paths_as_matches(
            graph,
            f"""
            MATCH p = (n:Account {{id: $id}})-[rs:{TRANSFER}*2..{_clamp(max_length, 2, 8)}]->()
            WHERE all(i IN range(0, size(rs) - 2) WHERE
                rs[i + 1].ts >= rs[i].ts
                AND rs[i + 1].ts <= rs[i].ts + duration({{hours: $gap}})
                AND rs[i + 1].amount >= $ratio * rs[i].amount)
            WITH p LIMIT 2000
            RETURN p ORDER BY length(p) DESC LIMIT $limit
            """,
            {"id": node_id, "gap": max_gap_hours, "ratio": min_forward_ratio,
             "limit": _clamp(limit, 1, 20)},
            chain_context=True,
        )
    return PatternResult(
        pattern=pattern,
        matches=matches,
        node_ids=unique([n for m in matches for n in m.node_ids]),
        rel_ids=unique([r for m in matches for r in m.rel_ids]),
    )


async def _fan(
    graph: GraphClient,
    pattern: str,
    node_id: str,
    window_days: float,
    min_count: int,
    min_amount: float | None,
    max_amount: float | None,
) -> list[PatternMatch]:
    """Best sliding time window of transfers in (fan_in) or out (fan_out) of the account."""
    arrow = "<-[t:TRANSFER]-(other)" if pattern == "fan_in" else "-[t:TRANSFER]->(other)"
    rows = await graph.read(
        f"""
        MATCH (n:Account {{id: $id}}){arrow}
        WHERE ($min IS NULL OR t.amount >= $min) AND ($max IS NULL OR t.amount <= $max)
        RETURN t.id AS id, other.id AS other, t.amount AS amount, t.ts AS ts
        ORDER BY ts LIMIT 5000
        """,
        id=node_id,
        min=min_amount,
        max=max_amount,
    )
    for row in rows:
        row["ts"] = row["ts"].to_native()
    window = timedelta(days=window_days)
    best: list[dict[str, Any]] = []
    start = 0
    for end in range(len(rows)):
        while rows[end]["ts"] - rows[start]["ts"] > window:
            start += 1
        current = rows[start : end + 1]
        if len({r["other"] for r in current}) > len({r["other"] for r in best}):
            best = current
    if len({r["other"] for r in best}) < min_count:
        return []
    others = unique([r["other"] for r in best])
    total = sum(r["amount"] for r in best)
    if pattern == "fan_out":  # the deposit that funded the payouts
        context = await graph.read(
            """
            MATCH (src)-[t:TRANSFER]->(n:Account {id: $id})
            WHERE t.ts >= $first - duration({hours: 48}) AND t.ts <= $first
              AND t.amount >= 0.5 * $total
            RETURN t.id AS id, src.id AS other ORDER BY t.amount DESC, t.id LIMIT 1
            """,
            id=node_id, first=best[0]["ts"], total=total,
        )
    else:  # where the collected money went next
        context = await graph.read(
            """
            MATCH (n:Account {id: $id})-[t:TRANSFER]->(dst)
            WHERE t.ts >= $last AND t.ts <= $last + duration({days: 3})
              AND t.amount >= 0.5 * $total
            RETURN t.id AS id, dst.id AS other ORDER BY t.amount DESC, t.id LIMIT 1
            """,
            id=node_id, last=best[-1]["ts"], total=total,
        )
    context_ids = [r["id"] for r in context]
    return [
        PatternMatch(
            node_ids=unique([node_id, *others, *(r["other"] for r in context)]),
            rel_ids=[r["id"] for r in best] + context_ids,
            transfer_count=len(best),
            counterparties=len(others),
            total_amount=round(total, 2),
            span_hours=round((best[-1]["ts"] - best[0]["ts"]).total_seconds() / 3600, 2),
            context_rel_ids=context_ids,
        )
    ]


async def _paths_as_matches(
    graph: GraphClient, query: str, params: dict[str, Any], chain_context: bool = False
) -> list[PatternMatch]:
    records, _ = await graph.read_records(query, params, timeout=15, max_rows=params["limit"])
    matches = []
    for record in records:
        path: Path = record["p"]
        times = [r["ts"].to_native() for r in path.relationships]
        view = path_view(path)
        context: list[dict[str, Any]] = []
        if chain_context:
            context = await _chain_context(graph, path, view)
        context_ids = [c["id"] for c in context]
        matches.append(
            PatternMatch(
                node_ids=unique([*view.node_ids, *(c["other"] for c in context)]),
                rel_ids=view.rel_ids + context_ids,
                transfer_count=len(view.rel_ids),
                counterparties=len(set(view.node_ids)) - 1,
                total_amount=round(sum(r["amount"] for r in path.relationships), 2),
                span_hours=round((max(times) - min(times)).total_seconds() / 3600, 2),
                context_rel_ids=context_ids,
            )
        )
    return matches


async def _chain_context(graph: GraphClient, path: Path, view: PathView) -> list[dict[str, Any]]:
    """The deposit that started a chain and the small side transfers skimmed at each hop."""
    hops = [
        {"node": view.node_ids[i], "ts": r["ts"], "amount": r["amount"]}
        for i, r in enumerate(path.relationships)
    ]
    return await graph.read(
        """
        CALL () {
          WITH $hops[0] AS first
          MATCH (src)-[t:TRANSFER]->(:Account {id: first.node})
          WHERE t.ts >= first.ts - duration({hours: 48}) AND t.ts <= first.ts
            AND t.amount >= first.amount
          RETURN t.id AS id, src.id AS other ORDER BY t.amount DESC, t.id LIMIT 1
          UNION
          UNWIND $hops AS hop
          MATCH (:Account {id: hop.node})-[t:TRANSFER]->(dst)
          WHERE NOT t.id IN $path_rels
            AND t.ts >= hop.ts - duration({hours: 48}) AND t.ts <= hop.ts + duration({hours: 48})
            AND t.amount <= 0.12 * hop.amount
          RETURN t.id AS id, dst.id AS other
        }
        RETURN id, other ORDER BY id
        """,
        hops=hops,
        path_rels=view.rel_ids,
    )


# --- graph_cypher_readonly ----------------------------------------------------------------


class CypherResult(ToolResult):
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool = False


async def cypher_readonly(
    graph: GraphClient,
    query: str,
    params: dict[str, Any] | None = None,
    row_cap: int = 100,
    timeout_s: float = 10,
) -> CypherResult:
    params = params or {}
    check_readonly(query)
    query_type, operators = await graph.explain(query, **params)
    if query_type != "r":
        raise CypherRejected("Neo4j classifies this query as a write")
    check_plan(operators)

    records, truncated = await graph.read_records(
        query, params, timeout=_clamp(int(timeout_s), 1, 30), max_rows=_clamp(row_cap, 1, 500)
    )
    node_ids: list[str] = []
    rel_ids: list[str] = []
    rows = [
        # A neo4j Record iterates over values, so the keys must be asked for explicitly.
        {key: _row_value(record[key], node_ids, rel_ids) for key in record.keys()}  # noqa: SIM118
        for record in records
    ]
    return CypherResult(
        columns=list(records[0].keys()) if records else [],
        rows=rows,
        truncated=truncated,
        node_ids=unique(node_ids),
        rel_ids=unique(rel_ids),
    )


def _row_value(value: Any, node_ids: list[str], rel_ids: list[str]) -> Any:
    """Make a row value JSON-safe, envelope free text, and collect every Lattice ID seen."""
    if isinstance(value, Node):
        view = node_view(value)
        node_ids.append(view.id)
        return view.model_dump()
    if isinstance(value, Relationship):
        view = rel_view(value)
        rel_ids.append(view.id)
        return view.model_dump()
    if isinstance(value, Path):
        view = path_view(value)
        node_ids.extend(view.node_ids)
        rel_ids.extend(view.rel_ids)
        return view.model_dump()
    if isinstance(value, list):
        return [_row_value(v, node_ids, rel_ids) for v in value]
    if isinstance(value, dict):
        return {k: _row_value(v, node_ids, rel_ids) for k, v in value.items()}
    if isinstance(value, str):
        try:
            kind = kind_of(value)
        except ValueError:
            return UntrustedText(content=value).model_dump()
        (rel_ids if kind == "transfer" else node_ids).append(value)
        return value
    if hasattr(value, "to_native"):
        return value.to_native().isoformat()
    return value
