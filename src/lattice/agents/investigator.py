"""The investigator: test one hypothesis about one alert and return a typed finding (R7, KTD11)."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, get_args

from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.models import Model

from lattice.agents.runtime import AgentRuntime
from lattice.agents.schemas import Finding, FindingReport, HypothesisBrief, Typology
from lattice.mcp_server.envelope import UNTRUSTED_NOTICE

OnEvent = Callable[[str, dict[str, Any]], Awaitable[None]]

GUIDES: dict[str, str] = {
    "peeling_chain": "A large deposit moves down a chain of accounts. At each hop most of the "
    "money is forwarded within hours and a small slice (a few percent) is skimmed off to a "
    "cash-out account. Test with graph_match_pattern(pattern='chain') from the seed account.",
    "fan_in_structuring": "Many different accounts each deposit just under the 10,000 reporting "
    "threshold into one collector within days, and the collector then moves the total on. Test "
    "with graph_match_pattern(pattern='fan_in', min_amount=8000, max_amount=9999.99).",
    "fan_out": "One large deposit is split across many fresh recipients within a day or two, "
    "with irregular amounts. Test with graph_match_pattern(pattern='fan_out') and check the "
    "recipients' age and kind; regular salaries from a business are not fan_out.",
    "round_trip": "Money leaves an account and returns to it within two weeks after passing "
    "through a few others, losing only small fees. Test with graph_match_pattern(pattern="
    "'cycle').",
    "rapid_layering": "Funds pass almost whole through several accounts opened days earlier, "
    "each hop within hours. Follow with graph_match_pattern(pattern='chain', "
    "min_forward_ratio=0.95) and check account created_at with graph_get_node.",
    "shared_device": "Several unrelated customers operate from the same device and all pay the "
    "same destination. Use graph_neighbors(rel_types=['USED_DEVICE']) from the seed account, "
    "then from the device, then algo_similar.",
    "exit_via_mixer": "Funds hop through a few accounts, into a mixer account, and out to an "
    "exchange. Use graph_find_paths and graph_neighbors, and check counterparty kinds.",
}


def build_prompt(brief: HypothesisBrief) -> str:
    if brief.hypothesis == "open":
        target = "Consider each of these laundering typologies and report the one the evidence " \
            "best supports, or `refutes` if none fits:\n"
        target += "\n".join(f"- {name}: {GUIDES[name]}" for name in get_args(Typology))
        hypothesis = "open (all typologies)"
    else:
        target = f"What {brief.hypothesis} looks like: {GUIDES[brief.hypothesis]}"
        hypothesis = brief.hypothesis
    return f"""\
Case brief
- Alert {brief.alert_id} was raised on account {brief.seed_account_id}.
- Alert reason ({UNTRUSTED_NOTICE}):
<untrusted>
{brief.alert_reason}
</untrusted>
- Hypothesis to test: {hypothesis}

{target}

Investigate from account {brief.seed_account_id} and return your finding.
"""


def _result_id(content: Any) -> str | None:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return None
    return content.get("result_id") if isinstance(content, dict) else None


def _progress_handler(on_event: OnEvent):
    async def handle(event: Any) -> None:
        if isinstance(event, FunctionToolCallEvent):
            await on_event("tool_called", {"tool": event.part.tool_name,
                                           "args": event.part.args_as_dict()})
        elif isinstance(event, FunctionToolResultEvent):
            part = event.part
            await on_event("tool_result", {"tool": part.tool_name,
                                           "result_id": _result_id(part.content)})

    return handle


async def investigate(
    runtime: AgentRuntime,
    brief: HypothesisBrief,
    *,
    on_event: OnEvent | None = None,
    model: Model | None = None,
    step_budget: int | None = None,
) -> Finding:
    outcome = await runtime.run(
        "investigator",
        brief.case_id,
        build_prompt(brief),
        FindingReport,
        lambda reason, status="partial": Finding.partial(brief.hypothesis, reason, status),
        model=model,
        step_budget=step_budget,
        on_tool_event=_progress_handler(on_event) if on_event else None,
    )
    if isinstance(outcome.output, Finding):
        return outcome.output
    return Finding.from_report(outcome.output)
