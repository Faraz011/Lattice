"""The sweeper: no case or approved action stays stuck (System-Wide Impact).

Runs alongside the orchestrator role. Each pass:
1. Verifies fan-ins whose deadline passed, with the findings that arrived (missing ones are
   recorded as failed), exactly once.
2. Redispatches cases untouched past the stall timeout, from their Neo4j record. This recovers
   cases whose jobs or fan-in state vanished with Redis.
3. Re-queues approved actions that never executed.
"""

import asyncio
import contextlib
import logging

import redis.asyncio as redis

from lattice.cases.actions import ActionStore
from lattice.cases.dispatch import first_job, hand_off_to_verifier
from lattice.cases.store import CaseStore
from lattice.config import Settings
from lattice.graph.client import GraphClient
from lattice.queue.fanin import FanIn
from lattice.queue.jobs import Job, Keys
from lattice.queue.streams import JobQueue

log = logging.getLogger(__name__)

RECOVERABLE = ["received", "planning", "investigating", "verifying"]


class Sweeper:
    def __init__(self, graph: GraphClient, client: redis.Redis, keys: Keys,
                 settings: Settings) -> None:
        self._cases = CaseStore(graph)
        self._actions = ActionStore(graph)
        self._fanin = FanIn(client, keys)
        self._queue = JobQueue(client, keys)
        self._settings = settings

    async def sweep_once(self) -> None:
        await self._deadlines()
        await self._stalled_cases()
        await self._stalled_actions()

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.sweep_once()
            except Exception:  # one bad pass must not stop recovery for good
                log.exception("sweep failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._settings.sweep_interval_s)

    async def _deadlines(self) -> None:
        for case_id in await self._fanin.due():
            if await self._fanin.claim(case_id):
                findings = await self._fanin.collect(case_id)
                log.info("deadline reached for %s with %d findings", case_id, len(findings))
                await hand_off_to_verifier(self._cases.save_findings, self._queue, case_id,
                                           findings)
                await self._cases.touch(case_id)

    async def _stalled_cases(self) -> None:
        stale = await self._cases.stalled(RECOVERABLE, self._settings.case_stall_timeout_s)
        for case in stale:
            if case["status"] == "investigating" and await self._fanin.exists(case["id"]):
                continue  # still collecting; the deadline pass owns it
            saved = await self._cases.saved_findings(case["id"])
            if case["status"] == "verifying" and saved:
                await hand_off_to_verifier(None, self._queue, case["id"], saved)
            else:
                await self._queue.enqueue(first_job(case))
            log.info("redispatched stalled case %s (%s)", case["id"], case["status"])
            await self._cases.touch(case["id"])

    async def _stalled_actions(self) -> None:
        for action in await self._actions.stalled_approved(self._settings.case_stall_timeout_s):
            await self._queue.enqueue(Job.new("execute_action", action["case_id"],
                                              {"action_id": action["id"]}))
            await self._actions.touch(action["id"])
