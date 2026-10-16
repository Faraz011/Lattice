"""A scripted stand-in for a language model: `LATTICE_MODEL=scripted`.

It is a fixed policy, not intelligence. It runs the whole pipeline offline (real MCP tools, real
ledger, real verifier) so the demo and the UI can be exercised without an API key:

- orchestrator: always tests the same four typologies;
- investigator: looks up the seed account, runs the hypothesis's pattern tool, and reports
  `supports` when the pattern matches from a non-business account, citing exactly what the tools
  returned;
- narrator: not scripted; the verifier uses the deterministic template instead.

Every verdict still comes from the risk scorer, so the circuit and counterfactuals are real.
"""

import json
import re
from typing import Any

from pydantic_ai import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.messages import ModelMessage, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

SCRIPTED = "scripted"
HYPOTHESES = ["peeling_chain", "fan_in_structuring", "fan_out", "round_trip"]

# The tool call that tests each typology, as (tool, arguments without the seed).
PLAN: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "peeling_chain": [("graph_match_pattern", {"pattern": "chain"})],
    "rapid_layering": [("graph_match_pattern", {"pattern": "chain", "min_forward_ratio": 0.95})],
    "fan_in_structuring": [("graph_match_pattern", {"pattern": "fan_in", "min_amount": 8000,
                                                    "max_amount": 9999.99})],
    "fan_out": [("graph_match_pattern", {"pattern": "fan_out", "min_count": 8})],
    "round_trip": [("graph_match_pattern", {"pattern": "cycle"})],
    "exit_via_mixer": [("graph_match_pattern", {"pattern": "chain"})],
    "shared_device": [("graph_neighbors", {"rel_types": ["USED_DEVICE"], "hops": 2})],
}
OPEN_ORDER = ["peeling_chain", "fan_in_structuring", "fan_out", "round_trip", "shared_device"]

SEED = re.compile(r"Investigate from account (\S+?)(?: and|\s|$)")
HYPOTHESIS = re.compile(r"Hypothesis to test: (\w+)")


def _prompt(messages: list[ModelMessage]) -> str:
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "user-prompt" and isinstance(part.content, str):
                return part.content
    return ""


def _returns(messages: list[ModelMessage]) -> list[tuple[str, dict]]:
    seen = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart):
                content = part.content
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except ValueError:
                        continue
                if isinstance(content, dict):
                    seen.append((part.tool_name, content))
    return seen


def _calls(hypothesis: str) -> list[tuple[str, dict[str, Any]]]:
    if hypothesis == "open":
        return [call for h in OPEN_ORDER for call in PLAN[h]]
    return PLAN.get(hypothesis, PLAN["peeling_chain"])


def _evidence(tool: str, result: dict) -> list[str]:
    if tool == "graph_match_pattern":
        return [r for m in result.get("matches", [])
                for r in [*m.get("rel_ids", []), *m.get("context_rel_ids", [])]]
    if tool == "graph_neighbors":
        links = [r for r in result.get("rel_ids", []) if r.startswith("used_device:")]
        return links if len(links) >= 3 else []
    return []


def _investigate(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    prompt = _prompt(messages)
    seed_match, hypothesis_match = SEED.search(prompt), HYPOTHESIS.search(prompt)
    seed = seed_match.group(1) if seed_match else ""
    hypothesis = hypothesis_match.group(1) if hypothesis_match else "open"
    done = _returns(messages)

    if not done:
        return ModelResponse(parts=[ToolCallPart("graph_get_node", {"node_id": seed})])
    plan = _calls(hypothesis)
    if len(done) - 1 < len(plan):
        tool, args = plan[len(done) - 1]
        return ModelResponse(parts=[ToolCallPart(tool, {"node_id": seed, **args})])

    node = done[0][1]
    business = (node.get("node", {}).get("props", {}).get("kind")) == "business"
    claims, found = [], []
    for (tool, result), (_, args) in zip(done[1:], plan, strict=False):
        rel_ids = list(dict.fromkeys(_evidence(tool, result)))
        if rel_ids:
            found.append(args.get("pattern", tool))
            claims.append({"statement": f"{tool} {args.get('pattern', '')} matched from {seed}",
                           "node_ids": [], "rel_ids": rel_ids,
                           "result_ids": [result.get("result_id", "")]})
    supports = bool(claims) and not business
    report = {
        "hypothesis": hypothesis,
        "verdict": "supports" if supports else "refutes",
        "confidence": 0.7 if supports else 0.6,
        "summary": (f"Scripted check: {', '.join(found)} matched from the seed account."
                    if supports else
                    "Scripted check: the pattern did not match from the seed account."),
        "claims": claims + [{"statement": "seed account record", "node_ids": [seed],
                             "rel_ids": [], "result_ids": [node.get("result_id", "")]}],
    }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, report)])


def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if not info.output_tools:
        return ModelResponse(parts=[TextPart("")])
    schema = json.dumps(info.output_tools[0].parameters_json_schema)
    if '"hypotheses"' in schema:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "hypotheses": HYPOTHESES, "rationale": "scripted run: the same four every time"})])
    return _investigate(messages, info)


def scripted_model() -> FunctionModel:
    return FunctionModel(_respond, model_name=SCRIPTED)
