"""Two copies of a worker role started as real processes share one stream (R9)."""

import asyncio
import os
import sys
import time

from lattice.queue.events import EventStream
from lattice.queue.jobs import Job
from lattice.queue.streams import JobQueue


async def test_two_copies_of_a_role_split_one_stream_between_them(redis_client, keys):
    env = {**os.environ, "LATTICE_REDIS_NAMESPACE": keys.namespace}
    procs = [
        await asyncio.create_subprocess_exec(
            sys.executable, "-m", "lattice.workers.main", "echo", "--name", name, env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        for name in ("copy-1", "copy-2")
    ]
    try:
        queue = JobQueue(redis_client, keys)
        events = EventStream(redis_client, keys)
        await asyncio.sleep(2)  # let both copies join the consumer group
        jobs = [Job.new("echo", case_id="case_roles", payload={"n": i}) for i in range(12)]
        for job in jobs:
            await queue.enqueue(job)

        deadline = time.monotonic() + 20
        echoed = []
        while time.monotonic() < deadline:
            echoed = [e for e in await events.read_all("case_roles") if e.type == "echo"]
            if len(echoed) == len(jobs):
                break
            await asyncio.sleep(0.2)
    finally:
        for proc in procs:
            proc.terminate()
            await proc.wait()

    assert sorted(e.data["job_id"] for e in echoed) == sorted(j.job_id for j in jobs)
    assert {e.data["worker"] for e in echoed} == {"copy-1", "copy-2"}
