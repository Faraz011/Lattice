"""Opt-in check against the real Gemini API: `uv run pytest -m live`. Spends rate budget."""

import pytest

from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Finding, FindingReport
from lattice.config import load_settings

PROMPT = """\
Hypothesis: fan_out. Tool results already gathered for account acct_hub (result_id led_1):
- tx_1: acct_hub received 50000.00 from an exchange at 09:00.
- tx_2..tx_13: acct_hub sent between 3500 and 4600 to 12 different accounts created this week,
  all between 10:00 and 22:00 the same day; together 49100.00.
Decide whether the evidence supports the fan_out hypothesis and cite the IDs.
"""


async def test_gemini_returns_a_schema_valid_finding():
    settings = load_settings()
    if not settings.gemini_api_key or not settings.gemini_api_key.get_secret_value():
        pytest.skip("set LATTICE_GEMINI_API_KEY in .env to run the live check")

    runtime = AgentRuntime(settings, mcp_url=None)
    outcome = await runtime.run(
        "investigator", "case_live", PROMPT, FindingReport,
        lambda reason, status="partial": Finding.partial("fan_out", reason, status),
        step_budget=3,
    )

    assert outcome.status == "complete", outcome.reason
    assert outcome.output.hypothesis == "fan_out"
    assert outcome.output.verdict == "supports"
    assert any("tx_" in r for c in outcome.output.claims for r in c.rel_ids)
