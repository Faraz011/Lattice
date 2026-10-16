"""One model-call budget shared by every worker (KTD2, R11).

A token bucket refilled at `per_minute` tokens a minute, plus an optional cap per UTC day, both
updated atomically in one Lua script using Redis's own clock, so copies of a worker on different
machines draw from the same budget.
"""

import asyncio
import time

import redis.asyncio as redis

# Returns {granted (0/1), wait_ms (-1 means the day's cap is spent)}.
_TAKE = """
local key, day_key = KEYS[1], KEYS[2]
local capacity, per_ms, per_day = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

if per_day > 0 and tonumber(redis.call('GET', day_key) or '0') >= per_day then
  return {0, -1}
end

local tokens = tonumber(redis.call('HGET', key, 'tokens'))
local last = tonumber(redis.call('HGET', key, 'ts'))
if tokens == nil then tokens = capacity; last = now end
tokens = math.min(capacity, tokens + (now - last) * per_ms)

local granted, wait = 0, 0
if tokens >= 1 then
  tokens = tokens - 1
  granted = 1
  if per_day > 0 then
    redis.call('INCR', day_key)
    redis.call('EXPIRE', day_key, 172800)
  end
else
  wait = math.ceil((1 - tokens) / per_ms)
end
redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', now)
redis.call('PEXPIRE', key, 3600000)
return {granted, wait}
"""


class RateLimiter:
    def __init__(
        self, client: redis.Redis, key: str, per_minute: int, per_day: int | None = None
    ) -> None:
        self._redis = client
        self._key = key
        self._per_minute = per_minute
        self._per_day = per_day or 0
        self._take = client.register_script(_TAKE)

    def _day_key(self) -> str:
        return f"{self._key}:day:{time.strftime('%Y-%m-%d', time.gmtime())}"

    async def acquire(self, timeout: float) -> bool:
        """Take one call's worth of budget, waiting at most `timeout` seconds for it."""
        deadline = time.monotonic() + timeout
        while True:
            granted, wait_ms = await self._take(
                keys=[self._key, self._day_key()],
                args=[self._per_minute, self._per_minute / 60_000, self._per_day],
            )
            if granted:
                return True
            remaining = deadline - time.monotonic()
            if wait_ms < 0 or remaining <= 0:
                return False
            await asyncio.sleep(min(wait_ms / 1000, remaining))

    async def remaining_today(self) -> int | None:
        if not self._per_day:
            return None
        used = int(await self._redis.get(self._day_key()) or 0)
        return max(0, self._per_day - used)
