"""The investigator end to end with a scripted model: real MCP server, real ledger, fixture world.

The script is a fixed policy, not intelligence: it looks up the seed account and its outgoing
transfers, tests the hypothesis's pattern, and says "supports" when the pattern matches from a
non-business account. That is enough to prove the plumbing: briefs in, ledger-backed findings out.
"""

import json
import uuid

import pytest
from pydantic_ai import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from lattice.agents.investigator import investigate
from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import HypothesisBrief
from lattice.config import load_settings
from lattice.datagen.injection import INJECTION_MEMOS

PATTERN = {"peeling_chain": "chain", "fan_out": "fan_out", "fan_in_structuring": "fan_in",
           "round_trip": "cycle", "rapid_layering": "chain", "exit_via_mixer": "chain",
           "shared_device": "fan_out"}


def returns(messages) -> dict[str, dict]:
    """Tool name -> structured result, from the tool returns seen so far."""
    seen = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart):
                content = part.content
                seen[part.tool_name] = json.loads(content) if isinstance(content, str) else content
    return seen


def scripted(seed: str, hypothesis: str, memos_seen: list[str]) -> FunctionModel:
    def script(messages, info: AgentInfo) -> ModelResponse:
        got = returns(messages)
        if "graph_get_node" not in got:
            return ModelResponse(parts=[ToolCallPart("graph_get_node", {"node_id": seed})])
        if "graph_neighbors" not in got:
            return ModelResponse(parts=[ToolCallPart(
                "graph_neighbors", {"node_id": seed, "direction": "out"})])
        if "graph_match_pattern" not in got:
            return ModelResponse(parts=[ToolCallPart(
                "graph_match_pattern", {"pattern": PATTERN[hypothesis], "node_id": seed,
                                        "min_count": 8})])

        node, neighbours, match = (got["graph_get_node"], got["graph_neighbors"],
                                   got["graph_match_pattern"])
        memos_seen.extend(text["memo"]["content"] for rel in neighbours["rels"]
                          for text in [rel.get("text", {})] if "memo" in text)
        matched = bool(match["matches"])
        business = node["node"]["props"]["kind"] == "business"
        verdict = "supports" if matched and not business else "refutes"
        rel_ids = match["matches"][0]["rel_ids"] if matched else []
        report = {
            "hypothesis": hypothesis, "verdict": verdict, "confidence": 0.8 if matched else 0.6,
            "summary": f"pattern matched={matched}, business sender={business}",
            "claims": [
                {"statement": "account kind", "node_ids": [seed], "rel_ids": [],
                 "result_ids": [node["result_id"]]},
                {"statement": "pattern match", "node_ids": [], "rel_ids": rel_ids,
                 "result_ids": [match["result_id"]]},
            ],
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, report)])

    return FunctionModel(script)


@pytest.fixture
async def case_id(graph):
    case = f"case_inv{uuid.uuid4().hex[:12]}"
    yield case
    await graph.write("MATCH (l:LedgerEntry {case_id: $c}) DELETE l", c=case)


def case_of(world, kind, category="planted", injected=False):
    return next(c for c in world.manifest.cases
                if c.kind == kind and c.category == category
                and bool(c.injected_transfer_id) == injected and not c.case_id.endswith("twin"))


async def run(mcp_server_url, case_id, record, hypothesis, memos=None):
    runtime = AgentRuntime(load_settings(), mcp_url=mcp_server_url)
    brief = HypothesisBrief(case_id=case_id, alert_id=record.alert_id,
                            seed_account_id=record.seed_account_id, alert_reason="test",
                            hypothesis=hypothesis)
    events: list[tuple[str, dict]] = []

    async def on_event(kind, data):
        events.append((kind, data))

    finding = await investigate(
        runtime, brief, on_event=on_event,
        model=scripted(record.seed_account_id, hypothesis, memos if memos is not None else []),
    )
    return finding, events


async def ledger_rel_ids(graph, case_id) -> set[str]:
    rows = await graph.read("MATCH (l:LedgerEntry {case_id: $c}) RETURN l.rel_ids AS r", c=case_id)
    return {r for row in rows for r in row["r"]}


async def test_a_planted_peeling_chain_is_supported_with_ledgered_citations(
    mcp_server_url, fixture_world, graph, case_id
):
    record = case_of(fixture_world, "peeling_chain")

    finding, _ = await run(mcp_server_url, case_id, record, "peeling_chain")

    assert finding.status == "complete"
    assert finding.verdict == "supports"
    cited = set(finding.evidence_rel_ids())
    assert len(cited & set(record.transfer_ids)) >= 3
    assert cited <= await ledger_rel_ids(graph, case_id)


async def test_a_payroll_decoy_refutes_the_fan_out_hypothesis(
    mcp_server_url, fixture_world, case_id
):
    record = case_of(fixture_world, "payroll_fan_out", category="decoy")

    finding, _ = await run(mcp_server_url, case_id, record, "fan_out")

    assert finding.verdict == "refutes"


async def test_an_injected_memo_does_not_change_the_verdict_of_its_twin_case(
    mcp_server_url, fixture_world, graph
):
    injected = next(c for c in fixture_world.manifest.cases
                    if c.injected_transfer_id and c.category == "planted")
    twin = next(c for c in fixture_world.manifest.cases if c.case_id == injected.twin_case_id)
    hypothesis = injected.kind
    memos: list[str] = []
    cases = [f"case_inj{uuid.uuid4().hex[:12]}", f"case_twn{uuid.uuid4().hex[:12]}"]
    try:
        with_memo, _ = await run(mcp_server_url, cases[0], injected, hypothesis, memos)
        without_memo, _ = await run(mcp_server_url, cases[1], twin, hypothesis)
    finally:
        for c in cases:
            await graph.write("MATCH (l:LedgerEntry {case_id: $c}) DELETE l", c=c)

    assert with_memo.verdict == without_memo.verdict
    seed_transfer = next(t for t in fixture_world.batch.transfers
                         if t.id == injected.injected_transfer_id)
    if seed_transfer.src == injected.seed_account_id:
        assert any(m in INJECTION_MEMOS for m in memos)  # the memo was seen, enveloped


async def test_tool_calls_and_results_are_reported_as_they_happen(
    mcp_server_url, fixture_world, case_id
):
    record = case_of(fixture_world, "fan_out")

    _, events = await run(mcp_server_url, case_id, record, "fan_out")

    calls = [d["tool"] for kind, d in events if kind == "tool_called"]
    results = [d for kind, d in events if kind == "tool_result"]
    assert calls == ["graph_get_node", "graph_neighbors", "graph_match_pattern"]
    assert [r["tool"] for r in results] == calls
    assert all(r["result_id"].startswith("led_") for r in results)
