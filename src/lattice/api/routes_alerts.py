"""Alerts and starting investigations (R3)."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lattice.api.state import Api
from lattice.cases.dispatch import first_job
from lattice.cases.store import CapExceeded, UnknownAlert

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
        await api.queue.enqueue(first_job(case))
    return JSONResponse(status_code=201 if created else 200,
                        content={"case": _public(case), "created": created})


def _public(case: dict) -> dict:
    out = {k: v for k, v in case.items() if k != "active_key"}
    for key in ("created_at", "updated_at"):
        if key in out and hasattr(out[key], "to_native"):
            out[key] = out[key].to_native().isoformat()
    return out
