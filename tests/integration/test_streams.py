"""Job streams against compose Redis. Each test runs in its own key namespace."""

import asyncio

import pytest

from lattice.queue.jobs import Job
from lattice.queue.streams import Consumer, JobQueue


async def drain(*consumers: Consumer, rounds: int = 10) -> None:
    for _ in range(rounds):
        await asyncio.gather(*(c.run_once(block_ms=50) for c in consumers))


async def test_two_consumers_in_one_group_never_receive_the_same_job(redis_client, keys):
    queue = JobQueue(redis_client, keys)
    seen: dict[str, list[str]] = {"a": [], "b": []}

    def handler(name):
        async def handle(job: Job) -> None:
            seen[name].append(job.job_id)
            await asyncio.sleep(0.01)
        return handle

    a = Consumer(redis_client, keys, "echo", "workers", "a", handler("a"))
    b = Consumer(redis_client, keys, "echo", "workers", "b", handler("b"))
    await a.ensure_group()
    jobs = [Job.new("echo", case_id="case_x") for _ in range(20)]
    for job in jobs:
        await queue.enqueue(job)

    await drain(a, b, rounds=30)

    assert sorted(seen["a"] + seen["b"]) == sorted(j.job_id for j in jobs)
    assert not set(seen["a"]) & set(seen["b"])
    assert seen["a"] and seen["b"]


async def test_a_job_whose_worker_died_is_reclaimed_by_another(redis_client, keys):
    queue = JobQueue(redis_client, keys)
    done: list[str] = []

    async def crash(job: Job) -> None:
        raise SystemExit("worker process died")

    async def finish(job: Job) -> None:
        done.append(job.job_id)

    dying = Consumer(redis_client, keys, "echo", "workers", "dying", crash, idle_ms=300)
    healthy = Consumer(redis_client, keys, "echo", "workers", "healthy", finish, idle_ms=300)
    await dying.ensure_group()
    job = Job.new("echo", case_id="case_x")
    await queue.enqueue(job)

    with pytest.raises(SystemExit):
        await dying.run_once(block_ms=100)
    await healthy.run_once(block_ms=50)
    assert done == []  # not yet idle long enough to reclaim
    await asyncio.sleep(0.4)
    await healthy.run_once(block_ms=50)

    assert done == [job.job_id]


async def test_a_heartbeating_long_job_is_not_handed_to_a_second_consumer(redis_client, keys):
    queue = JobQueue(redis_client, keys)
    started: list[str] = []

    async def slow(job: Job) -> None:
        started.append("slow")
        await asyncio.sleep(1.2)

    async def eager(job: Job) -> None:
        started.append("eager")

    owner = Consumer(redis_client, keys, "echo", "workers", "owner", slow,
                     idle_ms=300, heartbeat_ms=100)
    other = Consumer(redis_client, keys, "echo", "workers", "other", eager, idle_ms=300)
    await owner.ensure_group()
    await queue.enqueue(Job.new("echo", case_id="case_x"))

    async def poll_other():
        for _ in range(10):
            await asyncio.sleep(0.1)
            await other.run_once(block_ms=10)

    await asyncio.gather(owner.run_once(block_ms=100), poll_other())

    assert started == ["slow"]


async def test_a_job_failing_three_times_is_dead_lettered_with_its_error(redis_client, keys):
    queue = JobQueue(redis_client, keys)
    attempts: list[int] = []

    async def always_fails(job: Job) -> None:
        attempts.append(job.attempt)
        raise ValueError(f"bad payload on attempt {job.attempt}")

    consumer = Consumer(redis_client, keys, "echo", "workers", "w", always_fails, max_attempts=3)
    await consumer.ensure_group()
    job = Job.new("echo", case_id="case_x")
    await queue.enqueue(job)

    await drain(consumer, rounds=6)

    assert attempts == [0, 1, 2]
    dead = await queue.dead_letters()
    assert [d.job.job_id for d in dead] == [job.job_id]
    assert dead[0].error == "ValueError: bad payload on attempt 2"


async def test_redelivering_a_completed_job_is_a_no_op(redis_client, keys):
    queue = JobQueue(redis_client, keys)
    handled: list[str] = []

    async def handle(job: Job) -> None:
        handled.append(job.job_id)

    consumer = Consumer(redis_client, keys, "echo", "workers", "w", handle)
    await consumer.ensure_group()
    job = Job.new("echo", case_id="case_x")
    await queue.enqueue(job)
    await queue.enqueue(job)  # the same job delivered twice

    await drain(consumer, rounds=4)

    assert handled == [job.job_id]


async def test_a_transient_redis_error_does_not_stop_the_worker(redis_client, keys, monkeypatch):
    consumer = Consumer(redis_client, keys, "echo", group="echo", name="w1",
                        handler=lambda job: asyncio.sleep(0))
    stop = asyncio.Event()
    calls = 0

    async def flaky(block_ms):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("redis restarting")
        stop.set()
        return 0

    monkeypatch.setattr(consumer, "run_once", flaky)

    await asyncio.wait_for(consumer.run_forever(stop, retry_s=0.01), timeout=5)

    assert calls == 2
