"""Case details, evidence, the live event stream, recordings, and human review decisions."""

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from lattice.agents.schemas import Verdict
from lattice.api.sse import case_events
from lattice.api.state import Api, Approver
from lattice.cases.policy import InvalidTransition
from lattice.cases.proposals import propose_for_case
from lattice.cases.store import UnknownCase
from lattice.cases.views import case_evidence, case_view, public, record_case
from lattice.queue.replay import load_recording, load_snapshot
from lattice.queue.usage import UsageLedger

router = APIRouter()


async def _case(api: Api, case_id: str) -> dict:
    try:
        return await api.cases.get(case_id)
    except UnknownCase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_id}")
async def get_case(case_id: str, api: Api) -> dict:
    case = await _case(api, case_id)
    actions = [public(a) for a in await api.actions.for_case(case_id)]
    return {"case": case_view(case), "actions": actions}


@router.get("/cases/{case_id}/evidence")
async def get_evidence(case_id: str, api: Api) -> dict:
    case = await _case(api, case_id)
    return await case_evidence(api.graph, case_id, case.get("seed_account_id"))


@router.get("/cases/{case_id}/usage")
async def get_usage(case_id: str, api: Api) -> dict:
    """Model requests, cache hits and tokens per agent role (R21)."""
    await _case(api, case_id)
    return {"case_id": case_id, "roles": await UsageLedger(api.redis, api.keys).get(case_id)}


@router.get("/cases/{case_id}/events")
async def stream_events(
    case_id: str,
    api: Api,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    return StreamingResponse(
        case_events(api.events, case_id, after=last_event_id or "0-0"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/cases/{case_id}/recording", status_code=201)
async def save_recording(case_id: str, api: Api) -> dict:
    await _case(api, case_id)
    await record_case(api.graph, api.events, case_id)
    return await get_recording(case_id, api)


@router.get("/cases/{case_id}/recording")
async def get_recording(case_id: str, api: Api) -> dict:
    events = await load_recording(api.graph, case_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"no recording saved for {case_id}")
    return {"case_id": case_id, "events": [e.model_dump(mode="json") for e in events],
            "snapshot": await load_snapshot(api.graph, case_id)}


async def _review(api: Api, case_id: str, target: str, who: str) -> dict:
    try:
        case = await api.cases.get(case_id)
        if case["status"] != "needs_review":
            raise InvalidTransition(f"case is {case['status']}, not needs_review")
        if target == "awaiting_approval":
            # Escalation needs something to approve: propose before the case waits on it.
            await propose_for_case(api.graph, api.events, case, _verdict(case),
                                   f"escalated for approval by {who} after review")
        updated = await api.cases.transition(case_id, target, f"review decision by {who}")
    except UnknownCase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await api.events.publish(case_id, "review_decision", {"status": target, "by": who})
    if target == "closed_no_action":
        await record_case(api.graph, api.events, case_id)
    return {"case": case_view(updated)}


def _verdict(case: dict) -> Verdict | None:
    raw = case.get("verdict")
    return Verdict.model_validate_json(raw) if raw else None


@router.post("/cases/{case_id}/escalate")
async def escalate(case_id: str, who: Approver, api: Api) -> dict:
    return await _review(api, case_id, "awaiting_approval", who)


@router.post("/cases/{case_id}/clear")
async def clear(case_id: str, who: Approver, api: Api) -> dict:
    return await _review(api, case_id, "closed_no_action", who)
