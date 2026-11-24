"""The offline `scripted` model drives the real tools, and the scorer flags what it cites."""

import uuid

import pytest

from lattice.agents.investigator import investigate
from lattice.agents.orchestrator import choose_hypotheses
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import HypothesisBrief
from lattice.agents.scripted import HYPOTHESES
from lattice.config import load_settings
from lattice.graph.subgraph import load_evidence
from lattice.scoring.scorer import Scorer


@pytest.fixture
def runtime(mcp_server_url):
    settings = load_settings().model_copy(update={"model": "scripted", "role_models": {}})
    return AgentRuntime(settings, mcp_url=mcp_server_url)


@pytest.fixture
async def case_id(graph):
    case = f"case_scr{uuid.uuid4().hex[:12]}"
    yield case
    await graph.write("MATCH (l:LedgerEntry {case_id: $c}) DELETE l", c=case)


def planted(world, kind):
    return next(c for c in world.manifest.cases if c.kind == kind and c.category == "planted"
                and not c.injected_transfer_id and not c.case_id.endswith("twin"))


async def run(runtime, case_id, record, hypothesis):
    brief = HypothesisBrief(case_id=case_id, alert_id=record.alert_id,
                            seed_account_id=record.seed_account_id, alert_reason="test",
                            hypothesis=hypothesis)
    return await investigate(runtime, brief)


@pytest.mark.parametrize("kind", ["peeling_chain", "fan_in_structuring", "fan_out"])
async def test_a_scripted_investigation_of_a_planted_case_is_flagged_by_the_scorer(
    runtime, case_id, fixture_world, graph, kind
):
    record = planted(fixture_world, kind)

    finding = await run(runtime, case_id, record, kind)

    assert finding.status == "complete"
    assert finding.verdict == "supports"
    score = Scorer().score(await load_evidence(graph, finding.evidence_rel_ids()))
    assert score.score >= Scorer().threshold


async def test_the_open_hypothesis_tries_every_pattern(runtime, case_id, fixture_world):
    record = planted(fixture_world, "peeling_chain")

    finding = await run(runtime, case_id, record, "open")

    assert finding.verdict == "supports"
    assert finding.claims[-1].node_ids == [record.seed_account_id]


async def test_the_scripted_orchestrator_picks_its_fixed_hypotheses(runtime, case_id):
    assert await choose_hypotheses(runtime, case_id, "summary") == HYPOTHESES
