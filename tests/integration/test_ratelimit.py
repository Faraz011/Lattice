"""The shared model-call budget, against compose Redis."""

import asyncio
import json
import sys
import time

from lattice.queue.ratelimit import RateLimiter

CHILD = """
import asyncio, json, sys
import redis.asyncio as redis
from lattice.queue.ratelimit import RateLimiter

async def main(url, key, per_minute, attempts):
    client = redis.Redis.from_url(url, decode_responses=True)
    limiter = RateLimiter(client, key, per_minute=per_minute)
    results = await asyncio.gather(*(limiter.acquire(timeout=0.5) for _ in range(attempts)))
    await client.aclose()
    print(json.dumps(sum(results)))

asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])))
"""


async def run_child(url, key, per_minute, attempts) -> int:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", CHILD, url, key, str(per_minute), str(attempts),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, err.decode()
    return json.loads(out)


async def test_a_per_minute_budget_admits_exactly_n_across_two_processes(redis_url, keys):
    n = 8
    key = keys.limiter()

    granted = await asyncio.gather(
        run_child(redis_url, key, n, 7), run_child(redis_url, key, n, 6)
    )

    assert sum(granted) == n  # 13 attempts, budget 8


async def test_waiting_past_the_bound_reports_exhaustion_instead_of_blocking(redis_client, keys):
    limiter = RateLimiter(redis_client, keys.limiter(), per_minute=1)
    assert await limiter.acquire(timeout=0.1) is True

    started = time.monotonic()
    granted = await limiter.acquire(timeout=0.3)

    assert granted is False
    assert time.monotonic() - started < 1.0


async def test_a_waiting_caller_is_admitted_once_a_token_refills(redis_client, keys):
    limiter = RateLimiter(redis_client, keys.limiter(), per_minute=120)  # one token per 0.5 s
    for _ in range(120):
        assert await limiter.acquire(timeout=0) is True

    assert await limiter.acquire(timeout=2) is True


async def test_the_daily_cap_stops_calls_even_when_the_minute_budget_has_room(redis_client, keys):
    limiter = RateLimiter(redis_client, keys.limiter(), per_minute=100, per_day=3)

    results = [await limiter.acquire(timeout=0.2) for _ in range(5)]

    assert results == [True, True, True, False, False]
    assert await limiter.remaining_today() == 0
