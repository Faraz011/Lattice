from lattice.queue.llm_cache import LLMCache

MESSAGES = [{"role": "user", "content": "trace the funds from acct_1"}]
TOOLS = [{"name": "graph_neighbors", "parameters": {"node_id": "string"}}]


class CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        return f"response {self.calls}"


async def test_a_cache_hit_returns_the_stored_response_without_calling_the_model(
    redis_client, keys
):
    cache = LLMCache(redis_client, keys, ttl_s=60)
    model = CountingModel()

    first = await cache.cached("gemini-flash", MESSAGES, TOOLS, model)
    second = await cache.cached("gemini-flash", MESSAGES, TOOLS, model)

    assert first == second == "response 1"
    assert model.calls == 1


async def test_changing_the_tool_schema_misses_the_cache(redis_client, keys):
    cache = LLMCache(redis_client, keys, ttl_s=60)
    model = CountingModel()
    changed_tools = [{**TOOLS[0], "parameters": {"node_id": "string", "hops": "integer"}}]

    await cache.cached("gemini-flash", MESSAGES, TOOLS, model)
    await cache.cached("gemini-flash", MESSAGES, changed_tools, model)

    assert model.calls == 2


async def test_changing_the_model_or_messages_misses_the_cache(redis_client, keys):
    cache = LLMCache(redis_client, keys, ttl_s=60)
    model = CountingModel()

    await cache.cached("gemini-flash", MESSAGES, TOOLS, model)
    await cache.cached("gemini-pro", MESSAGES, TOOLS, model)
    await cache.cached("gemini-flash", [*MESSAGES, {"role": "user", "content": "more"}], TOOLS,
                       model)

    assert model.calls == 3


async def test_a_disabled_cache_always_calls_the_model(redis_client, keys):
    cache = LLMCache(redis_client, keys, ttl_s=60, enabled=False)
    model = CountingModel()

    await cache.cached("gemini-flash", MESSAGES, TOOLS, model)
    await cache.cached("gemini-flash", MESSAGES, TOOLS, model)

    assert model.calls == 2


async def test_cached_entries_expire(redis_client, keys):
    cache = LLMCache(redis_client, keys, ttl_s=60)
    await cache.cached("gemini-flash", MESSAGES, TOOLS, CountingModel())

    key = cache.key("gemini-flash", MESSAGES, TOOLS)
    assert 0 < await redis_client.ttl(key) <= 60
