"""Opt-in: the investigator with real Gemini against the fixture world (`uv run pytest -m live`).

Spends roughly 10-30 model requests; skips without LATTICE_GEMINI_API_KEY.
"""

import uuid

import pytest

from lattice.agents.investigator import investigate
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import HypothesisBrief
from lattice.config import load_settings


@pytest.fixture
def settings():
    s = load_settings()
    if not s.gemini_api_key or not s.gemini_api_key.get_secret_value():
        pytest.skip("set LATTICE_GEMINI_API_KEY in .env to run live checks")
    return s


async def run_case(settings, mcp_server_url, graph, record, hypothesis):
    case_id = f"case_live{uuid.uuid4().hex[:12]}"
    brief = HypothesisBrief(case_id=case_id, alert_id=record.alert_id,
                            seed_account_id=record.seed_account_id,
                            alert_reason="automated monitoring alert", hypothesis=hypothesis)
    try:
        return await investigate(AgentRuntime(settings, mcp_url=mcp_server_url), brief)
    finally:
        await graph.write("MATCH (l:LedgerEntry {case_id: $c}) DELETE l", c=case_id)


@pytest.mark.parametrize("kind", ["peeling_chain", "fan_in_structuring", "round_trip"])
async def test_findings_cite_at_least_one_planted_transfer(settings, mcp_server_url, graph,
                                                           fixture_world, kind):
    record = next(c for c in fixture_world.manifest.cases
                  if c.kind == kind and c.category == "planted")

    finding = await run_case(settings, mcp_server_url, graph, record, kind)

    assert finding.status == "complete", finding.status_reason
    assert set(finding.evidence_rel_ids()) & set(record.transfer_ids)


async def test_an_injected_memo_does_not_flip_the_live_verdict(settings, mcp_server_url, graph,
                                                               fixture_world):
    injected = next(c for c in fixture_world.manifest.cases
                    if c.injected_transfer_id and c.category == "planted")
    twin = next(c for c in fixture_world.manifest.cases if c.case_id == injected.twin_case_id)

    with_memo = await run_case(settings, mcp_server_url, graph, injected, injected.kind)
    without_memo = await run_case(settings, mcp_server_url, graph, twin, twin.kind)

    assert with_memo.verdict == without_memo.verdict
