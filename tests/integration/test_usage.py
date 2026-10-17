"""Model usage counters per case and role, and the API that serves them to the harness."""

import uuid

import httpx
from pydantic import SecretStr

from lattice.api.app import create_app
from lattice.cases.store import CaseStore
from lattice.config import load_settings
from lattice.queue.ratelimit import RateLimiter
from lattice.queue.usage import UsageLedger


async def test_counts_add_up_per_role(redis_client, keys):
    ledger = UsageLedger(redis_client, keys)
    case_id = f"case_use{uuid.uuid4().hex[:10]}"

    await ledger.add(case_id, "investigator", requests=1, input_tokens=100, output_tokens=20)
    await ledger.add(case_id, "investigator", requests=1, input_tokens=50, output_tokens=5)
    await ledger.add(case_id, "investigator", cached=1)
    await ledger.add(case_id, "narrator", requests=1, input_tokens=10, output_tokens=40)

    usage = await ledger.get(case_id)

    assert usage["investigator"] == {"requests": 2, "cached": 1, "input_tokens": 150,
                                     "output_tokens": 25}
    assert usage["narrator"]["output_tokens"] == 40
    assert await ledger.get("case_none") == {}


async def test_the_api_serves_a_cases_usage(redis_client, keys, graph, fixture_world, serve_app):
    settings = load_settings().model_copy(update={
        "redis_namespace": keys.namespace, "approver_token": SecretStr("t"),
        "max_active_cases": 1_000, "max_cases_per_day": 100_000})
    record = next(c for c in fixture_world.manifest.cases if c.kind == "fan_out")
    case, _ = await CaseStore(graph).start(record.alert_id, "single", 1_000, 100_000)
    try:
        await UsageLedger(redis_client, keys).add(case["id"], "investigator", requests=3)
        base, stop = serve_app(create_app(settings))
        try:
            async with httpx.AsyncClient(base_url=base) as http:
                body = (await http.get(f"/cases/{case['id']}/usage")).json()
                missing = await http.get("/cases/case_doesnotexist00/usage")
        finally:
            stop()
    finally:
        await graph.write("MATCH (c:Case {id: $id}) DETACH DELETE c", id=case["id"])

    assert body["roles"]["investigator"]["requests"] == 3
    assert missing.status_code == 404


async def test_the_api_reports_the_shared_budget_the_workers_use(redis_client, keys, serve_app):
    settings = load_settings().model_copy(update={
        "redis_namespace": keys.namespace, "approver_token": SecretStr("t"),
        "llm_requests_per_day": 40})
    limiter = RateLimiter(redis_client, keys.limiter(), 60, 40)
    for _ in range(3):
        assert await limiter.acquire(timeout=1)
    base, stop = serve_app(create_app(settings))
    try:
        async with httpx.AsyncClient(base_url=base) as http:
            budget = (await http.get("/budget")).json()
    finally:
        stop()

    assert budget["per_day"] == 40
    assert budget["remaining_today"] == 37
    assert budget["case_room"] == max(0, settings.max_cases_per_day - budget["cases_today"])
