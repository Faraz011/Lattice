"""Job queues on Redis Streams consumer groups (KTD3).

Lifecycle of one message:
- A consumer reads it through its group; only that consumer owns it.
- While the handler runs, a heartbeat re-claims the message to its owner, so long LLM-bound
  jobs are never mistaken for stalled ones.
- Success: the job ID is marked done and the message is acked. A later duplicate is a no-op.
- Handler error: the job is re-queued with `attempt + 1`, or dead-lettered after
  `max_attempts`, and the original is acked.
- Worker death: the message stays pending, and after `idle_ms` another consumer reclaims it.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from pydantic import BaseModel

from lattice.queue.jobs import Job, Keys

log = logging.getLogger(__name__)

Handler = Callable[[Job], Awaitable[None]]
DONE_TTL_S = 7 * 24 * 3600


class DeadLetter(BaseModel):
    job: Job
    error: str


class JobQueue:
    def __init__(self, client: redis.Redis, keys: Keys) -> None:
        self._redis = client
        self._keys = keys

    async def enqueue(self, job: Job) -> str:
        return await self._redis.xadd(self._keys.stream(job.type), job.to_fields())

    async def dead_letters(self) -> list[DeadLetter]:
        entries = await self._redis.xrange(self._keys.dead_letter())
        return [
            DeadLetter(job=Job.from_fields(fields), error=fields["error"]) for _, fields in entries
        ]


class Consumer:
    def __init__(
        self,
        client: redis.Redis,
        keys: Keys,
        job_type: str,
        group: str,
        name: str,
        handler: Handler,
        *,
        idle_ms: int = 30_000,
        heartbeat_ms: int = 10_000,
        max_attempts: int = 3,
    ) -> None:
        self._redis = client
        self._keys = keys
        self._stream = keys.stream(job_type)
        self._group = group
        self.name = name
        self._handler = handler
        self._idle_ms = idle_ms
        self._heartbeat_ms = heartbeat_ms
        self._max_attempts = max_attempts
        self._queue = JobQueue(client, keys)

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run_once(self, block_ms: int = 5_000) -> int:
        """Process reclaimed stale messages, then at most one new one. Returns how many ran."""
        await self.ensure_group()
        _, reclaimed, _ = await self._redis.xautoclaim(
            self._stream, self._group, self.name, min_idle_time=self._idle_ms, count=10
        )
        messages = [(msg_id, fields) for msg_id, fields in reclaimed if fields]
        if not messages:
            response = await self._redis.xreadgroup(
                self._group, self.name, {self._stream: ">"}, count=1, block=block_ms
            )
            messages = [m for _, entries in response for m in entries]
        for msg_id, fields in messages:
            await self._process(msg_id, fields)
        return len(messages)

    async def run_forever(self, stop: asyncio.Event, retry_s: float = 2.0) -> None:
        while not stop.is_set():
            try:
                await self.run_once(block_ms=1_000)
            except Exception:  # Redis restarting or a dropped connection: wait and carry on
                log.exception("%s: reading %s failed; retrying in %.0fs",
                              self.name, self._stream, retry_s)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=retry_s)

    async def _process(self, msg_id: str, fields: dict[str, str]) -> None:
        job = Job.from_fields(fields)
        if await self._redis.exists(self._keys.done(job.job_id)):
            await self._redis.xack(self._stream, self._group, msg_id)
            return

        heartbeat = asyncio.create_task(self._heartbeat(msg_id))
        try:
            await self._handler(job)
        except Exception as exc:  # a handler bug or bad input; worker death is not caught
            await self._fail(job, exc)
        else:
            await self._redis.set(self._keys.done(job.job_id), "1", ex=DONE_TTL_S)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        await self._redis.xack(self._stream, self._group, msg_id)

    async def _fail(self, job: Job, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"
        if job.attempt + 1 >= self._max_attempts:
            log.error("dead-lettering job %s after %d attempts: %s",
                      job.job_id, job.attempt + 1, error)
            await self._redis.xadd(self._keys.dead_letter(), {**job.to_fields(), "error": error})
        else:
            log.warning("retrying job %s (attempt %d): %s", job.job_id, job.attempt + 1, error)
            await self._queue.enqueue(job.retried())

    async def _heartbeat(self, msg_id: str) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_ms / 1000)
            await self._redis.xclaim(
                self._stream, self._group, self.name, min_idle_time=0,
                message_ids=[msg_id], justid=True,
            )
