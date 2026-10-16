"""Model response cache (KTD2): the same model, messages and tool schema reuse one response.

Re-running a case after a code change only spends quota on the calls that actually changed.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis

from lattice.queue.jobs import Keys


class LLMCache:
    def __init__(
        self, client: redis.Redis, keys: Keys, ttl_s: int, enabled: bool = True
    ) -> None:
        self._redis = client
        self._keys = keys
        self._ttl_s = ttl_s
        self.enabled = enabled

    def key(self, model: str, messages: Any, tools: Any) -> str:
        canonical = json.dumps(
            {"model": model, "messages": messages, "tools": tools}, sort_keys=True, default=str
        )
        return self._keys.cache(hashlib.sha256(canonical.encode()).hexdigest())

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key) if self.enabled else None

    async def put(self, key: str, response: str) -> None:
        if self.enabled:
            await self._redis.set(key, response, ex=self._ttl_s)

    async def cached(
        self, model: str, messages: Any, tools: Any, call: Callable[[], Awaitable[str]]
    ) -> str:
        key = self.key(model, messages, tools)
        hit = await self.get(key)
        if hit is not None:
            return hit
        response = await call()
        await self.put(key, response)
        return response
