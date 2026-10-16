"""Shared clients for API requests, and the approver check."""

import hmac
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, Header, HTTPException, Request

from lattice.cases.actions import ActionStore
from lattice.cases.store import CaseStore
from lattice.config import Settings
from lattice.graph.client import GraphClient
from lattice.queue.events import EventStream
from lattice.queue.jobs import Keys
from lattice.queue.streams import JobQueue


@dataclass
class ApiState:
    settings: Settings
    graph: GraphClient
    redis: redis.Redis
    keys: Keys
    events: EventStream
    queue: JobQueue
    cases: CaseStore
    actions: ActionStore


def state(request: Request) -> ApiState:
    return request.app.state.api


def approver(
    request: Request,
    x_approver_token: str | None = Header(default=None),
    x_approver_name: str | None = Header(default=None),
) -> str:
    """Require the shared approver token; returns a name for the audit trail."""
    expected = state(request).settings.approver_token.get_secret_value()
    if not x_approver_token or not hmac.compare_digest(x_approver_token, expected):
        raise HTTPException(status_code=401, detail="a valid X-Approver-Token is required")
    return x_approver_name or "approver"


Api = Annotated[ApiState, Depends(state)]
Approver = Annotated[str, Depends(approver)]
