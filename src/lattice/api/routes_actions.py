"""Human approval and rejection of proposed actions (R16, R17, KTD9)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lattice.api.routes_alerts import _public
from lattice.api.state import Api, Approver
from lattice.cases.actions import ActionStateError, UnknownAction
from lattice.queue.jobs import Job

router = APIRouter()


class RejectRequest(BaseModel):
    reason: str = "rejected by approver"


@router.post("/actions/{action_id}/approve")
async def approve(action_id: str, who: Approver, api: Api) -> dict:
    try:
        action = await api.actions.approve(action_id, who)
    except UnknownAction as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await api.queue.enqueue(Job.new("execute_action", action["case_id"],
                                    {"action_id": action_id}))
    await api.events.publish(action["case_id"], "action_approved",
                             {"action_id": action_id, "by": who})
    return {"action": _public(action)}


@router.post("/actions/{action_id}/reject")
async def reject(action_id: str, who: Approver, api: Api,
                 body: RejectRequest | None = None) -> dict:
    reason = (body or RejectRequest()).reason
    try:
        action = await api.actions.reject(action_id, who, reason)
    except UnknownAction as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case = await api.cases.get(action["case_id"])
    if case["status"] == "awaiting_approval":
        await api.cases.transition(case["id"], "rejected", reason)
    await api.events.publish(action["case_id"], "action_rejected",
                             {"action_id": action_id, "by": who, "reason": reason})
    return {"action": _public(action)}
