"""Model usage per case and role: requests, cache hits and tokens (R21).

Every agent request adds to its case's counters in one Redis hash, from whichever worker made
it. The evaluation harness reads them through the API to report tokens and cost per case.
"""

from collections import defaultdict

import redis.asyncio as redis

from lattice.queue.jobs import Keys

USAGE_TTL_S = 30 * 24 * 3600
FIELDS = ("requests", "cached", "input_tokens", "output_tokens")


class UsageLedger:
    def __init__(self, client: redis.Redis, keys: Keys) -> None:
        self._redis = client
        self._keys = keys

    async def add(self, case_id: str, role: str, *, requests: int = 0, cached: int = 0,
                  input_tokens: int = 0, output_tokens: int = 0) -> None:
        key = self._keys.usage(case_id)
        counts = {"requests": requests, "cached": cached, "input_tokens": input_tokens,
                  "output_tokens": output_tokens}
        async with self._redis.pipeline(transaction=True) as pipe:
            for field, value in counts.items():
                if value:
                    pipe.hincrby(key, f"{role}:{field}", value)
            pipe.expire(key, USAGE_TTL_S)
            await pipe.execute()

    async def get(self, case_id: str) -> dict[str, dict[str, int]]:
        """{role: {requests, cached, input_tokens, output_tokens}} for the case."""
        raw = await self._redis.hgetall(self._keys.usage(case_id))
        usage: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
        for name, value in raw.items():
            role, _, field = str(name).rpartition(":")
            usage[role][field] = int(value)
        return dict(usage)
