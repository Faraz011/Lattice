"""Case details, the live event stream, and human review decisions."""

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from lattice.api.routes_alerts import _public
from lattice.api.sse import case_events
from lattice.api.state import Api, Approver
from lattice.cases.policy import InvalidTransition
from lattice.cases.store import UnknownCase

router = APIRouter()


@router.get("/cases/{case_id}")
async def get_case(case_id: str, api: Api) -> dict:
    try:
        case = await api.cases.get(case_id)
    except UnknownCase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    actions = [_public(a) for a in await api.actions.for_case(case_id)]
    return {"case": _public(case), "actions": actions}


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


async def _review(api: Api, case_id: str, target: str, who: str) -> dict:
    try:
        case = await api.cases.get(case_id)
        if case["status"] != "needs_review":
            raise InvalidTransition(f"case is {case['status']}, not needs_review")
        updated = await api.cases.transition(case_id, target, f"review decision by {who}")
    except UnknownCase as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await api.events.publish(case_id, "review_decision", {"status": target, "by": who})
    return {"case": _public(updated)}


@router.post("/cases/{case_id}/escalate")
async def escalate(case_id: str, who: Approver, api: Api) -> dict:
    return await _review(api, case_id, "awaiting_approval", who)


@router.post("/cases/{case_id}/clear")
async def clear(case_id: str, who: Approver, api: Api) -> dict:
    return await _review(api, case_id, "closed_no_action", who)
