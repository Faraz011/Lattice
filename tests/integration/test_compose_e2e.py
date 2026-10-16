"""The full stack in containers: one planted alert end to end, and a worker lost mid-case.

Needs the application roles running, with the fixture world loaded and the offline model:

    uv run python -m lattice.datagen.cli --world fixture --load
    LATTICE_MODEL=scripted docker compose --profile app up -d --build
    uv run pytest -m compose
"""

import asyncio
import subprocess
import time

import httpx
import pytest

from lattice.config import load_settings
from lattice.eval.fixture_check import release

pytestmark = pytest.mark.compose

API = "http://localhost:8080"
E2E_TARGET_S = 300  # Success Criteria: alert to awaiting_approval within five minutes
FLAGGED = ("awaiting_approval", "needs_review")
FINAL = (*FLAGGED, "closed_no_action", "actioned", "rejected")


@pytest.fixture(scope="module", autouse=True)
def stack_is_up():
    try:
        httpx.get(f"{API}/health", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("the compose app stack is not running on localhost:8080")


def planted(fixture_world, kind, index=0):
    return [c for c in fixture_world.manifest.cases
            if c.kind == kind and c.category == "planted" and not c.injected_transfer_id
            and not c.case_id.endswith("twin")][index]


async def start(http, alert_id):
    response = await http.post(f"/alerts/{alert_id}/investigate", json={"mode": "orchestrated"})
    assert response.status_code in (200, 201), response.text
    return response.json()["case"]["id"]


async def wait_for(http, case_id, statuses, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        case = (await http.get(f"/cases/{case_id}")).json()["case"]
        if case["status"] in statuses:
            return case
        await asyncio.sleep(2)
    raise AssertionError(f"{case_id} still {case['status']} after {timeout_s}s")


def compose(*args):
    subprocess.run(["docker", "compose", "--profile", "app", *args], check=True,
                   capture_output=True)


async def test_a_planted_alert_reaches_approval_within_the_target(fixture_world):
    async with httpx.AsyncClient(base_url=API, timeout=30) as http:
        case_id = await start(http, planted(fixture_world, "peeling_chain").alert_id)
        started = time.monotonic()

        case = await wait_for(http, case_id, FINAL, E2E_TARGET_S)

        assert case["status"] == "awaiting_approval"
        assert time.monotonic() - started < E2E_TARGET_S
        assert case["circuit"]["circuit"]["status"] == "circuit"
        actions = (await http.get(f"/cases/{case_id}")).json()["actions"]
        assert actions and actions[0]["blast_radius"]["account_count"] > 0
        recording = await http.get(f"/cases/{case_id}/recording")
        assert recording.status_code == 200
        await release(http, case_id, load_settings().approver_token.get_secret_value())


async def test_losing_an_investigator_mid_case_still_yields_a_verdict(fixture_world):
    async with httpx.AsyncClient(base_url=API, timeout=30) as http:
        case_id = await start(http, planted(fixture_world, "fan_in_structuring").alert_id)
        await wait_for(http, case_id, ("investigating", *FINAL), 60)
        try:
            # One replica dies holding a hypothesis job; the other reclaims it once it idles.
            subprocess.run(["docker", "kill", "lattice-investigator-1"], check=True,
                           capture_output=True)
            case = await wait_for(http, case_id, FINAL, E2E_TARGET_S)
        finally:
            compose("up", "-d", "--no-deps", "investigator")
        await release(http, case_id, load_settings().approver_token.get_secret_value())

        assert case["verdict"] is not None
        assert case["status"] in FINAL
