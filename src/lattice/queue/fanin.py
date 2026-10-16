"""Fan-in of per-hypothesis findings (KTD11), held in Redis and updated atomically.

Each investigator records its finding as it finishes. The recording that completes the set,
or the sweeper when the deadline passes, wins a one-time claim and hands the case to the
verifier, so verification is enqueued exactly once however the findings race.
"""

import json
import time

import redis.asyncio as redis

from lattice.agents.schemas import Finding
from lattice.queue.jobs import Keys

STATE_TTL_S = 7 * 24 * 3600

# Returns 1 when this call completed the set and claimed the hand-off, 0 otherwise,
# -1 when no fan-in is open for the case.
_RECORD = """
local meta, received, findings, sent = KEYS[1], KEYS[2], KEYS[3], KEYS[4]
if redis.call('EXISTS', meta) == 0 then return -1 end
if redis.call('SADD', received, ARGV[1]) == 1 then
  redis.call('HSET', findings, ARGV[1], ARGV[2])
end
redis.call('EXPIRE', received, ARGV[3])
redis.call('EXPIRE', findings, ARGV[3])
local expected = cjson.decode(redis.call('HGET', meta, 'expected'))
if redis.call('SCARD', received) >= #expected then
  if redis.call('SET', sent, '1', 'NX', 'EX', ARGV[3]) then return 1 end
end
return 0
"""


class FanIn:
    def __init__(self, client: redis.Redis, keys: Keys) -> None:
        self._redis = client
        self._keys = keys
        self._record = client.register_script(_RECORD)

    def _k(self, case_id: str, part: str) -> str:
        return self._keys.fanin(case_id, part)

    async def open(self, case_id: str, expected: list[str], deadline_s: float) -> None:
        """Start (or restart) collecting findings for these hypotheses."""
        deadline = time.time() + deadline_s
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(*(self._k(case_id, p) for p in ("meta", "received", "findings", "sent")))
            pipe.hset(self._k(case_id, "meta"),
                      mapping={"expected": json.dumps(expected), "deadline": deadline})
            pipe.expire(self._k(case_id, "meta"), STATE_TTL_S)
            pipe.zadd(self._keys.fanin_deadlines(), {case_id: deadline})
            await pipe.execute()

    async def exists(self, case_id: str) -> bool:
        return bool(await self._redis.exists(self._k(case_id, "meta")))

    async def handed_off(self, case_id: str) -> bool:
        """The set completed (or its deadline passed) and verification was enqueued."""
        return bool(await self._redis.exists(self._k(case_id, "sent")))

    async def record(self, case_id: str, hypothesis: str, finding: Finding) -> bool:
        """Store a finding; True when this call completed the set and must hand off."""
        keys = [self._k(case_id, p) for p in ("meta", "received", "findings", "sent")]
        result = await self._record(
            keys=keys, args=[hypothesis, finding.model_dump_json(), STATE_TTL_S]
        )
        if result == 1:
            await self._redis.zrem(self._keys.fanin_deadlines(), case_id)
        return result == 1

    async def due(self) -> list[str]:
        """Cases whose deadline has passed and that are still waiting for findings."""
        return await self._redis.zrangebyscore(self._keys.fanin_deadlines(), 0, time.time())

    async def claim(self, case_id: str) -> bool:
        """Claim the hand-off at the deadline; False when it already happened."""
        await self._redis.zrem(self._keys.fanin_deadlines(), case_id)
        return bool(await self._redis.set(self._k(case_id, "sent"), "1", nx=True,
                                          ex=STATE_TTL_S))

    async def collect(self, case_id: str) -> list[Finding]:
        """Every finding received, plus a failed placeholder for each one that never came."""
        meta = await self._redis.hgetall(self._k(case_id, "meta"))
        expected = json.loads(meta.get("expected", "[]"))
        stored = await self._redis.hgetall(self._k(case_id, "findings"))
        findings = [Finding.model_validate_json(stored[h]) for h in expected if h in stored]
        findings += [
            Finding.partial(h, "no finding arrived before the deadline", "failed")
            for h in expected if h not in stored
        ]
        return findings
