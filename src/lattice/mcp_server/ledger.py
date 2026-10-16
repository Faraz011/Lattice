"""The evidence ledger (R5, KTD4, KTD5).

The server, not the agent, records every successful tool call: which case asked, what it asked
for, and exactly which node and relationship IDs came back. Verdicts may only cite IDs that
appear here, so an agent cannot invent evidence.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from lattice.graph.client import GraphClient
from lattice.ids import new_id


class ToolResult(BaseModel):
    """Fields every tool result carries; `result_id` is the ledger entry that recorded it."""

    result_id: str = ""
    node_ids: list[str] = []
    rel_ids: list[str] = []


R = TypeVar("R", bound=ToolResult)


class MissingCaseContext(PermissionError):
    """A tool was called outside an investigation."""


@dataclass(frozen=True)
class ToolContext:
    graph: GraphClient
    case_id: str


async def run_tool(
    ctx: ToolContext, tool: str, params: dict[str, Any], call: Callable[[], Awaitable[R]]
) -> R:
    """Run a tool for a case and ledger the result. Failed calls leave no entry."""
    if not ctx.case_id:
        raise MissingCaseContext("tool calls need a case context (X-Lattice-Case-Id header)")
    result = await call()
    result.result_id = new_id("ledger")
    await ctx.graph.write(
        """
        CREATE (:LedgerEntry {
          result_id: $result_id, case_id: $case_id, tool: $tool, params: $params,
          node_ids: $node_ids, rel_ids: $rel_ids, ts: datetime()
        })
        """,
        result_id=result.result_id,
        case_id=ctx.case_id,
        tool=tool,
        params=json.dumps(params, sort_keys=True, default=str),
        node_ids=result.node_ids,
        rel_ids=result.rel_ids,
    )
    return result
