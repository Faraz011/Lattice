"""Case records in Neo4j (KTD5): one per investigation, at most one active per alert.

`active_key` holds the alert ID while a case is open and is cleared when it ends. A uniqueness
constraint on it makes "start an investigation" atomic and idempotent per alert.
"""

from typing import Any

from lattice.agents.schemas import Finding
from lattice.cases.policy import TERMINAL_STATES, check_transition
from lattice.graph.client import GraphClient
from lattice.ids import new_id


class CapExceeded(RuntimeError):
    """Starting another investigation would pass a configured cap."""


class UnknownAlert(LookupError):
    pass


class UnknownCase(LookupError):
    pass


class CaseStore:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def start(
        self, alert_id: str, mode: str, max_active: int, max_per_day: int
    ) -> tuple[dict[str, Any], bool]:
        """Return (case, created). An open case for the alert is returned unchanged."""
        existing = await self._graph.read(
            "MATCH (c:Case {active_key: $alert}) RETURN c", alert=alert_id
        )
        if existing:
            return dict(existing[0]["c"]), False

        alerts = await self._graph.read(
            "MATCH (a:Alert {id: $alert}) RETURN a.seed_account_id AS seed, a.reason AS reason",
            alert=alert_id,
        )
        if not alerts:
            raise UnknownAlert(f"no alert {alert_id}")

        counts = (await self._graph.read(
            """
            MATCH (c:Case)
            RETURN count(CASE WHEN c.active_key IS NOT NULL THEN 1 END) AS active,
                   count(CASE WHEN c.created_at >= datetime() - duration('P1D') THEN 1 END)
                     AS today
            """
        ))[0]
        if counts["active"] >= max_active:
            raise CapExceeded(f"{counts['active']} investigations are already open "
                              f"(limit {max_active})")
        if counts["today"] >= max_per_day:
            raise CapExceeded(f"{counts['today']} investigations started in the last day "
                              f"(limit {max_per_day})")

        rows = await self._graph.write(
            """
            MERGE (c:Case {active_key: $alert})
            ON CREATE SET c.id = $id, c.alert_id = $alert, c.seed_account_id = $seed,
                          c.mode = $mode, c.alert_reason = $reason, c.status = 'received',
                          c.created_at = datetime(),
                          c.updated_at = datetime(), c._created = true
            WITH c, coalesce(c._created, false) AS created
            REMOVE c._created
            RETURN c, created
            """,
            alert=alert_id,
            id=new_id("case"),
            seed=alerts[0]["seed"],
            reason=alerts[0]["reason"],
            mode=mode,
        )
        return dict(rows[0]["c"]), rows[0]["created"]

    async def get(self, case_id: str) -> dict[str, Any]:
        rows = await self._graph.read("MATCH (c:Case {id: $id}) RETURN c", id=case_id)
        if not rows:
            raise UnknownCase(f"no case {case_id}")
        return dict(rows[0]["c"])

    async def transition(self, case_id: str, target: str, reason: str) -> dict[str, Any]:
        case = await self.get(case_id)
        check_transition(case["status"], target)
        rows = await self._graph.write(
            """
            MATCH (c:Case {id: $id}) WHERE c.status = $current
            SET c.status = $target, c.status_reason = $reason, c.updated_at = datetime(),
                c.active_key = CASE WHEN $terminal THEN null ELSE c.active_key END
            RETURN c
            """,
            id=case_id,
            current=case["status"],
            target=target,
            reason=reason,
            terminal=target in TERMINAL_STATES,
        )
        if not rows:  # someone else moved it first
            return await self.transition(case_id, target, reason)
        return dict(rows[0]["c"])

    async def save_findings(self, case_id: str, findings: list[Finding]) -> None:
        payload = "[" + ",".join(f.model_dump_json() for f in findings) + "]"
        await self._graph.write("MATCH (c:Case {id: $id}) SET c.findings = $findings",
                                id=case_id, findings=payload)

    async def saved_findings(self, case_id: str) -> list[Finding]:
        import json

        case = await self.get(case_id)
        return [Finding.model_validate(f) for f in json.loads(case.get("findings") or "[]")]

    async def stalled(self, statuses: list[str], older_than_s: float) -> list[dict[str, Any]]:
        rows = await self._graph.read(
            """
            MATCH (c:Case) WHERE c.status IN $statuses
              AND c.updated_at < datetime() - duration({seconds: $s})
            RETURN c ORDER BY c.updated_at
            """,
            statuses=statuses,
            s=older_than_s,
        )
        return [dict(r["c"]) for r in rows]

    async def touch(self, case_id: str) -> None:
        await self._graph.write("MATCH (c:Case {id: $id}) SET c.updated_at = datetime()",
                                id=case_id)

    async def list_alerts(self) -> list[dict[str, Any]]:
        return await self._graph.read(
            """
            MATCH (a:Alert)
            OPTIONAL MATCH (c:Case {alert_id: a.id})
            WITH a, c ORDER BY c.created_at DESC
            WITH a, collect(c)[0] AS latest
            OPTIONAL MATCH (r:Recording)
              WHERE EXISTS { MATCH (:Case {id: r.case_id, alert_id: a.id}) }
            WITH a, latest, r ORDER BY r.recorded_at DESC
            WITH a, latest, collect(r.case_id)[0] AS recorded
            RETURN a.id AS id, a.seed_account_id AS seed_account_id, a.reason AS reason,
                   a.ts AS ts, latest.id AS case_id, latest.status AS case_status,
                   recorded AS recorded_case_id
            ORDER BY a.ts DESC
            """
        )
