"""Start one worker role: `python -m lattice.workers.main <role> [--name NAME]` (R9, KTD12).

Every copy of a role joins the same consumer group, so running more copies splits the role's
stream between them with no code change.
"""

import argparse
import asyncio
import contextlib
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio as redis

from lattice.config import Settings, load_settings
from lattice.logging import configure_logging
from lattice.queue.events import EventStream
from lattice.queue.jobs import Job, Keys
from lattice.queue.streams import Consumer, Handler


@dataclass
class RoleContext:
    settings: Settings
    redis: redis.Redis
    keys: Keys
    events: EventStream
    worker_name: str


@dataclass(frozen=True)
class Role:
    job_type: str
    build_handler: Callable[[RoleContext], Awaitable[Handler]]


async def _echo_handler(ctx: RoleContext) -> Handler:
    """No-op role for checking deployment and scaling: reports which copy took each job."""

    async def handle(job: Job) -> None:
        await asyncio.sleep(float(job.payload.get("sleep", 0.1)))
        await ctx.events.publish(job.case_id, "echo",
                                 {"job_id": job.job_id, "worker": ctx.worker_name})

    return handle


async def _investigator_handler(ctx: RoleContext) -> Handler:
    from lattice.workers.investigator_worker import build_handler

    return await build_handler(ctx)


async def _action_handler(ctx: RoleContext) -> Handler:
    from lattice.workers.action_worker import build_handler

    return await build_handler(ctx)


ROLES: dict[str, Role] = {
    "echo": Role(job_type="echo", build_handler=_echo_handler),
    "investigator": Role(job_type="hypothesis", build_handler=_investigator_handler),
    "action": Role(job_type="execute_action", build_handler=_action_handler),
}


async def run(role_name: str, worker_name: str) -> None:
    settings = load_settings()
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    keys = Keys(settings.redis_namespace)
    ctx = RoleContext(settings, client, keys, EventStream(client, keys), worker_name)
    role = ROLES[role_name]
    consumer = Consumer(
        client,
        keys,
        role.job_type,
        group=role_name,
        name=worker_name,
        handler=await role.build_handler(ctx),
        idle_ms=int(settings.job_idle_timeout_s * 1000),
        heartbeat_ms=int(settings.job_heartbeat_s * 1000),
        max_attempts=settings.job_max_attempts,
    )

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows has no loop signal handlers; there the process is simply terminated.
        with contextlib.suppress(NotImplementedError):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await consumer.run_forever(stop)
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="lattice.workers.main")
    parser.add_argument("role", choices=sorted(ROLES))
    parser.add_argument("--name", default=f"{socket.gethostname()}-{os.getpid()}")
    args = parser.parse_args()
    configure_logging()
    asyncio.run(run(args.role, args.name))


if __name__ == "__main__":
    main()
