"""How graph elements appear in tool results: stable IDs, structured props, enveloped text."""

from typing import Any

from neo4j.graph import Node, Path, Relationship
from pydantic import BaseModel

from lattice.ids import link_id
from lattice.mcp_server.envelope import UntrustedText, quarantine


class NodeView(BaseModel):
    id: str
    labels: list[str]
    props: dict[str, Any]
    text: dict[str, UntrustedText] = {}


class RelView(BaseModel):
    id: str
    type: str
    src: str
    dst: str
    props: dict[str, Any]
    text: dict[str, UntrustedText] = {}


class PathView(BaseModel):
    node_ids: list[str]
    rel_ids: list[str]


def node_view(node: Node) -> NodeView:
    props, text = quarantine(dict(node))
    return NodeView(id=node["id"], labels=sorted(node.labels), props=props, text=text)


def rel_view(rel: Relationship, src: str | None = None, dst: str | None = None) -> RelView:
    src = src or rel.start_node["id"]
    dst = dst or rel.end_node["id"]
    props, text = quarantine(dict(rel))
    return RelView(
        id=rel.get("id") or link_id(rel.type, src, dst),
        type=rel.type,
        src=src,
        dst=dst,
        props=props,
        text=text,
    )


def path_view(path: Path) -> PathView:
    return PathView(
        node_ids=[n["id"] for n in path.nodes],
        rel_ids=[rel_view(r).id for r in path.relationships],
    )


def unique(ids: list[str]) -> list[str]:
    """De-duplicate while keeping first-seen order."""
    return list(dict.fromkeys(ids))
