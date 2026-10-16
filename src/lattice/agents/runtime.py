"""Build and run a Pydantic AI agent for any role (R10, R11, KTD1, KTD2, KTD4).

- The MCP toolset connects with the case ID in a header, so the model never chooses or even
  sees which case its evidence is ledgered under.
- Every model request goes through `BudgetedModel`: a cache lookup first, then a token from the
  shared rate limiter.
- The step budget caps model requests per run.
- Running out of either budget, or producing output that never validates, ends the run with a
  typed partial or failed result instead of an exception.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic_ai import (
    Agent,
    ModelMessagesTypeAdapter,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UsageLimits,
)
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import HandleResponseEvent, ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from lattice.agents.provider import build_model, model_for_role
from lattice.config import Settings
from lattice.mcp_server.server import CASE_HEADER

PROMPTS = Path(__file__).parent / "prompts"
OUTPUT_RETRIES = 2
# Fields that differ between otherwise identical requests and must not split the cache.
_VOLATILE = frozenset({"timestamp", "run_id", "conversation_id", "tool_call_id",
                       "provider_response_id", "provider_details", "usage"})

T = TypeVar("T")
ToolEventHandler = Callable[[HandleResponseEvent], Awaitable[None]]


# MCP tools no agent may call. Proposing an action is the verifier's job, after scoring.
AGENT_HIDDEN_TOOLS = frozenset({"case_propose_action"})

class Limiter(Protocol):
    async def acquire(self, timeout: float) -> bool: ...


class ResponseCache(Protocol):
    def key(self, model: str, messages: Any, tools: Any) -> str: ...
    async def get(self, key: str) -> str | None: ...
    async def put(self, key: str, value: str) -> None: ...


class BudgetExhausted(RuntimeError):
    """The shared model-call budget had no token within the wait bound."""


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


class BudgetedModel(WrapperModel):
    """Wraps any model with the response cache and the shared rate limiter."""

    def __init__(
        self,
        wrapped: Model,
        limiter: Limiter | None,
        cache: ResponseCache | None,
        wait_timeout_s: float,
    ) -> None:
        super().__init__(wrapped)
        self._limiter = limiter
        self._cache = cache
        self._wait_timeout_s = wait_timeout_s

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        key = None
        if self._cache is not None:
            key = self._cache.key(
                self.wrapped.model_name,
                _stable(ModelMessagesTypeAdapter.dump_python(messages, mode="json")),
                _tool_schema(model_request_parameters),
            )
            hit = await self._cache.get(key)
            if hit is not None:
                return ModelMessagesTypeAdapter.validate_json(hit)[0]

        if self._limiter is not None and not await self._limiter.acquire(self._wait_timeout_s):
            raise BudgetExhausted("the shared model rate budget is exhausted")

        response = await super().request(messages, model_settings, model_request_parameters)
        if key is not None:
            await self._cache.put(key, ModelMessagesTypeAdapter.dump_json([response]).decode())
        return response

    @asynccontextmanager
    async def request_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        # Streaming would go straight to the wrapped model, past the cache and the limiter.
        raise NotImplementedError("Lattice agents never stream model responses")
        yield


def _tool_schema(params: ModelRequestParameters) -> list[dict[str, Any]]:
    tools = [*params.function_tools, *params.output_tools]
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters_json_schema}
        for t in tools
    ]


def load_prompt(role: str) -> str:
    parts = [(PROMPTS / "common.md").read_text()]
    role_file = PROMPTS / f"{role}.md"
    if role_file.exists():
        parts.append(role_file.read_text())
    return "\n\n".join(parts)


@dataclass
class RunOutcome(Generic[T]):
    output: T
    status: Literal["complete", "budget_exhausted", "failed"]
    reason: str | None = None
    requests: int = 0


class AgentRuntime:
    def __init__(
        self,
        settings: Settings,
        mcp_url: str | None,
        limiter: Limiter | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self._settings = settings
        self._mcp_url = mcp_url
        self._limiter = limiter
        self._cache = cache

    def build_agent(
        self, role: str, case_id: str, output_type: type[T], model: Model | None = None
    ) -> Agent[None, T]:
        base = model or build_model(model_for_role(role, self._settings), self._settings)
        toolsets = []
        if self._mcp_url:
            # "failed": a tool error (unknown ID, rejected Cypher) goes back to the model as a
            # result it can read and recover from, instead of a retry that ends the run.
            mcp = MCPToolset(self._mcp_url, headers={CASE_HEADER: case_id},
                             tool_error_behavior="failed")
            # Agents investigate; only the verifier and reviewers propose actions (R16).
            toolsets.append(mcp.filtered(lambda _ctx, tool: tool.name not in AGENT_HIDDEN_TOOLS))
        return Agent(
            BudgetedModel(base, self._limiter, self._cache, self._settings.llm_wait_timeout_s),
            output_type=output_type,
            instructions=load_prompt(role),
            toolsets=toolsets,
            retries=OUTPUT_RETRIES,
        )

    async def run(
        self,
        role: str,
        case_id: str,
        prompt: str,
        output_type: type[T],
        partial: Callable[..., Any],
        *,
        model: Model | None = None,
        step_budget: int | None = None,
        on_tool_event: ToolEventHandler | None = None,
    ) -> RunOutcome[Any]:
        """Run one agent to a typed result. `partial(reason, status)` builds the fallback.

        `on_tool_event` receives each tool call and tool result as it happens, for live
        progress. Model requests themselves are never streamed (see `BudgetedModel`).
        """
        agent = self.build_agent(role, case_id, output_type, model)
        limits = UsageLimits(request_limit=step_budget or self._settings.investigation_step_budget)
        try:
            async with agent.iter(prompt, usage_limits=limits) as agent_run:
                async for node in agent_run:
                    if on_tool_event and Agent.is_call_tools_node(node):
                        async with node.stream(agent_run.ctx) as events:
                            async for event in events:
                                await on_tool_event(event)
            result = agent_run.result
        except UsageLimitExceeded as exc:
            reason = f"step budget reached ({exc})"
            return RunOutcome(partial(reason), "budget_exhausted", reason)
        except BudgetExhausted as exc:
            reason = f"rate budget exhausted ({exc})"
            return RunOutcome(partial(reason), "budget_exhausted", reason)
        except UnexpectedModelBehavior as exc:
            reason = f"output never validated: {exc}"
            return RunOutcome(partial(reason, "failed"), "failed", reason)
        return RunOutcome(result.output, "complete", requests=result.usage.requests)
