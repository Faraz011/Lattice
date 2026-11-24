"""Action records and their simulated execution (R16, R17, KTD9).

Agents create actions in `proposed` status (see `case_propose_action`). Only the API records
approvals and rejections, and only the action executor sets `executed` or `refused`.
"""

import json
from datetime import UTC, datetime
from typing import Any

from lattice.graph.client import GraphClient

SIMULATED_OUTCOMES = {
    "annotate": "note added to {target}",
    "escalate": "case on {target} escalated to the financial crime team (simulated)",
    "draft_report": "suspicious activity report drafted for {target} (simulated)",
    "freeze": "account {target} frozen (simulated)",
}


class ActionStateError(RuntimeError):
    """The action is not in a state that allows this change."""


class UnknownAction(LookupError):
    pass


class ActionStore:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def get(self, action_id: str) -> dict[str, Any]:
        rows = await self._graph.read("MATCH (a:Action {id: $id}) RETURN a", id=action_id)
        if not rows:
            raise UnknownAction(f"no action {action_id}")
        action = dict(rows[0]["a"])
        if action.get("blast_radius"):
            action["blast_radius"] = json.loads(action["blast_radius"])
        return action

    async def for_case(self, case_id: str) -> list[dict[str, Any]]:
        rows = await self._graph.read(
            "MATCH (a:Action {case_id: $id}) RETURN a.id AS id ORDER BY a.created_at", id=case_id
        )
        return [await self.get(r["id"]) for r in rows]

    async def stalled_approved(self, older_than_s: float) -> list[dict[str, Any]]:
        rows = await self._graph.read(
            """
            MATCH (a:Action {status: 'approved'})
            WHERE a.updated_at < datetime() - duration({seconds: $s})
            RETURN a.id AS id
            """,
            s=older_than_s,
        )
        return [await self.get(r["id"]) for r in rows]

    async def touch(self, action_id: str) -> None:
        await self._graph.write("MATCH (a:Action {id: $id}) SET a.updated_at = datetime()",
                                id=action_id)

    async def set_blast_radius(self, action_id: str, impact: dict[str, Any]) -> None:
        await self._graph.write(
            "MATCH (a:Action {id: $id}) SET a.blast_radius = $impact",
            id=action_id,
            impact=json.dumps(impact),
        )

    async def _move(
        self, action_id: str, from_status: str, to_status: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        rows = await self._graph.write(
            """
            MATCH (a:Action {id: $id}) WHERE a.status = $from
            SET a.status = $to, a.updated_at = datetime(), a += $fields
            RETURN a.id AS id
            """,
            id=action_id,
            **{"from": from_status, "to": to_status, "fields": fields},
        )
        if not rows:
            action = await self.get(action_id)
            raise ActionStateError(
                f"action {action_id} is {action['status']}, not {from_status}"
            )
        return await self.get(action_id)

    async def approve(self, action_id: str, approver: str) -> dict[str, Any]:
        action = await self.get(action_id)
        if action["tier"] >= 2 and not action.get("blast_radius"):
            raise ActionStateError("the blast radius must be computed before approval")
        return await self._move(action_id, "proposed", "approved",
                                {"approved_by": approver,
                                 "approved_at": datetime.now(UTC).isoformat()})

    async def reject(self, action_id: str, approver: str, reason: str) -> dict[str, Any]:
        return await self._move(action_id, "proposed", "rejected",
                                {"rejected_by": approver, "rejection_reason": reason})

    async def mark_executed(self, action: dict[str, Any]) -> dict[str, Any]:
        outcome = SIMULATED_OUTCOMES[action["kind"]].format(target=action["target_id"])
        return await self._move(action["id"], action["status"], "executed", {"outcome": outcome})

    async def mark_refused(self, action: dict[str, Any], reason: str) -> dict[str, Any]:
        return await self._move(action["id"], action["status"], "refused",
                                {"refusal_reason": reason})

