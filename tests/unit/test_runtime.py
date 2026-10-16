"""The agent runtime with deterministic models and a local stand-in MCP server (no Neo4j)."""

import socket
import threading
import time

import pytest
import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel

from lattice.agents.provider import build_model
from lattice.agents.runtime import AgentRuntime, BudgetedModel
from lattice.agents.schemas import Finding, FindingReport
from lattice.config import Settings
from lattice.mcp_server.server import CASE_HEADER

# --- a stand-in MCP server that records what each call carried ----------------------------

calls: list[dict] = []
fake = MCPServer("fake-graph")


@fake.tool(name="graph_neighbors", description="Neighbours of a node.")
async def graph_neighbors(node_id: str, ctx: Context) -> dict:
    headers = {k.lower(): v for k, v in (ctx.headers or {}).items()}
    calls.append({"args": {"node_id": node_id}, "case_id": headers.get(CASE_HEADER)})
    return {"result_id": f"led_{len(calls)}", "node_ids": [node_id], "rel_ids": ["tx_1"]}


@pytest.fixture(scope="module")
def mcp_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = fake.streamable_http_app(stateless_http=True, json_response=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(autouse=True)
def reset_calls():
    calls.clear()


def settings(**overrides) -> Settings:
    base = dict(
        neo4j_uri="bolt://x", neo4j_user="neo4j", neo4j_password="pw",
        redis_url="redis://x", approver_token="t", gemini_api_key="test-gemini-key",
        anthropic_api_key="test-anthropic-key",
    )
    return Settings(_env_file=None, **(base | overrides))


REPORT = {
    "hypothesis": "fan_out",
    "verdict": "supports",
    "confidence": 0.8,
    "summary": "hub pays many fresh accounts within a day",
    "claims": [{"statement": "hub paid acct_2", "rel_ids": ["tx_1"], "node_ids": [],
                "result_ids": ["led_1"]}],
}


def partial(reason: str, status: str = "partial") -> Finding:
    return Finding.partial("fan_out", reason, status)


class AlwaysExhausted:
    async def acquire(self, timeout: float) -> bool:
        return False


class DictCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def key(self, model, messages, tools) -> str:
        return repr((model, messages, tools))

    async def get(self, key):
        return self.store.get(key)

    async def put(self, key, value):
        self.store[key] = value


# --- tests --------------------------------------------------------------------------------


async def test_tool_calls_carry_the_injected_case_id_which_the_model_never_supplies(mcp_url):
    seen_tools: list = []

    def script(messages, info: AgentInfo) -> ModelResponse:
        seen_tools.extend(info.function_tools)
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("graph_neighbors", {"node_id": "acct_1"})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, REPORT)])

    runtime = AgentRuntime(settings(), mcp_url=mcp_url)
    outcome = await runtime.run("investigator", "case_abc", "investigate acct_1", FindingReport,
                                partial, model=FunctionModel(script))

    assert outcome.status == "complete"
    assert calls == [{"args": {"node_id": "acct_1"}, "case_id": "case_abc"}]
    schema = next(t for t in seen_tools if t.name == "graph_neighbors").parameters_json_schema
    assert "case_id" not in schema.get("properties", {})


async def test_reaching_the_step_budget_returns_a_partial_finding(mcp_url):
    def never_finishes(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("graph_neighbors", {"node_id": "acct_1"})])

    runtime = AgentRuntime(settings(), mcp_url=mcp_url)
    outcome = await runtime.run("investigator", "case_abc", "go", FindingReport, partial,
                                model=FunctionModel(never_finishes), step_budget=3)

    assert outcome.status == "budget_exhausted"
    assert isinstance(outcome.output, Finding)
    assert outcome.output.status == "partial"
    assert "step budget" in outcome.output.status_reason
    assert len(calls) <= 3


async def test_an_exhausted_rate_budget_returns_a_partial_result_instead_of_raising():
    runtime = AgentRuntime(settings(), mcp_url=None, limiter=AlwaysExhausted())

    outcome = await runtime.run("investigator", "case_abc", "go", FindingReport, partial,
                                model=TestModel())

    assert outcome.status == "budget_exhausted"
    assert outcome.output.status == "partial"
    assert "rate budget" in outcome.output.status_reason


async def test_output_that_keeps_failing_the_schema_ends_as_a_typed_failure():
    attempts = 0

    def bad_output(messages, info: AgentInfo) -> ModelResponse:
        nonlocal attempts
        attempts += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                 {**REPORT, "confidence": 5})])

    runtime = AgentRuntime(settings(), mcp_url=None)
    outcome = await runtime.run("investigator", "case_abc", "go", FindingReport, partial,
                                model=FunctionModel(bad_output))

    assert outcome.status == "failed"
    assert outcome.output.status == "failed"
    assert attempts > 1  # the framework retried before giving up


async def test_a_cache_hit_skips_the_model_and_the_limiter():
    model_calls = 0

    def answer(messages, info: AgentInfo) -> ModelResponse:
        nonlocal model_calls
        model_calls += 1
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, REPORT)])

    cache = DictCache()
    runtime = AgentRuntime(settings(), mcp_url=None, cache=cache)
    first = await runtime.run("investigator", "case_1", "same prompt", FindingReport, partial,
                              model=FunctionModel(answer))
    runtime_without_budget = AgentRuntime(settings(), mcp_url=None, cache=cache,
                                          limiter=AlwaysExhausted())
    second = await runtime_without_budget.run("investigator", "case_2", "same prompt",
                                              FindingReport, partial, model=FunctionModel(answer))

    assert model_calls == 1
    assert first.output == second.output


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("google:gemini-flash-latest", GoogleModel),
        ("anthropic:claude-sonnet-5-5", AnthropicModel),
        ("test", TestModel),
    ],
)
def test_the_model_string_alone_selects_the_provider(model, expected):
    assert isinstance(build_model(model, settings()), expected)


def test_a_role_override_picks_a_different_provider_for_that_role_only():
    runtime = AgentRuntime(
        settings(role_models={"verifier": "anthropic:claude-sonnet-5-5"}), mcp_url=None
    )

    verifier = runtime.build_agent("verifier", "case_1", FindingReport)
    investigator = runtime.build_agent("investigator", "case_1", FindingReport)

    assert isinstance(verifier.model, BudgetedModel)
    assert isinstance(verifier.model.wrapped, AnthropicModel)
    assert isinstance(investigator.model.wrapped, GoogleModel)
