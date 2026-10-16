"""Alerts and starting investigations (R3)."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lattice.api.state import Api
from lattice.cases.store import CapExceeded, UnknownAlert
from lattice.queue.jobs import Job

router = APIRouter()


class InvestigateRequest(BaseModel):
    # "single": one investigator considers every typology (Phase 2).
    # "orchestrated": the orchestrator fans out per-hypothesis investigators (U11).
    mode: Literal["single", "orchestrated"] = "single"


@router.get("/alerts")
async def list_alerts(api: Api) -> dict:
    alerts = await api.cases.list_alerts()
    for alert in alerts:
        alert["ts"] = alert["ts"].to_native().isoformat() if alert["ts"] else None
    return {"alerts": alerts}


@router.post("/alerts/{alert_id}/investigate")
async def investigate(
    alert_id: str, api: Api, body: InvestigateRequest | None = None
) -> JSONResponse:
    mode = (body or InvestigateRequest()).mode
    try:
        case, created = await api.cases.start(
            alert_id, mode, api.settings.max_active_cases, api.settings.max_cases_per_day
        )
    except UnknownAlert as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CapExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    if created:
        await api.events.publish(case["id"], "case_started",
                                 {"alert_id": alert_id, "mode": mode})
        await api.queue.enqueue(_first_job(case, mode))
    return JSONResponse(status_code=201 if created else 200,
                        content={"case": _public(case), "created": created})


def _first_job(case: dict, mode: str) -> Job:
    if mode == "orchestrated":
        return Job.new("investigate", case["id"], {"alert_id": case["alert_id"]})
    brief = {
        "case_id": case["id"],
        "alert_id": case["alert_id"],
        "seed_account_id": case["seed_account_id"],
        "alert_reason": case.get("alert_reason") or "",
        "hypothesis": "open",
    }
    return Job.new("hypothesis", case["id"], {"brief": brief, "single_agent": True})


def _public(case: dict) -> dict:
    out = {k: v for k, v in case.items() if k != "active_key"}
    for key in ("created_at", "updated_at"):
        if key in out and hasattr(out[key], "to_native"):
            out[key] = out[key].to_native().isoformat()
    return out
