"""Jobs that move a case forward, shared by the API, the workers and the sweeper."""

from typing import Any, Protocol

from lattice.agents.schemas import Finding
from lattice.queue.jobs import Job


class Enqueuer(Protocol):
    async def enqueue(self, job: Job) -> Any: ...


def first_job(case: dict[str, Any]) -> Job:
    """The job that starts (or restarts) a case's investigation, by its mode."""
    if case.get("mode") == "orchestrated":
        return Job.new("investigate", case["id"], {"alert_id": case["alert_id"]})
    brief = {
        "case_id": case["id"],
        "alert_id": case["alert_id"],
        "seed_account_id": case["seed_account_id"],
        "alert_reason": case.get("alert_reason") or "",
        "hypothesis": "open",
    }
    return Job.new("hypothesis", case["id"], {"brief": brief, "single_agent": True})


async def hand_off_to_verifier(
    save_findings, queue: Enqueuer, case_id: str, findings: list[Finding]
) -> None:
    """Persist the findings on the case first, so a lost verify job can be re-created."""
    if save_findings is not None:
        await save_findings(case_id, findings)
    await queue.enqueue(Job.new("verify", case_id,
                                {"findings": [f.model_dump(mode="json") for f in findings]}))
