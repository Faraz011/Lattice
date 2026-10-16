"""Action tiers and the case lifecycle (R16, R17).

Tier 0-1 actions run automatically; tier 2-3 need a recorded human approval. The executor asks
`execution_refusal` before every execution, whatever route the job took to reach it.
"""

from typing import Any, Literal

ActionKind = Literal["annotate", "escalate", "draft_report", "freeze"]

ACTION_TIERS: dict[str, int] = {
    "annotate": 1,
    "escalate": 2,
    "draft_report": 2,
    "freeze": 3,
}

CaseStatus = Literal[
    "received", "planning", "investigating", "verifying", "needs_review",
    "awaiting_approval", "closed_no_action", "actioned", "rejected",
]
TERMINAL_STATES = frozenset({"closed_no_action", "actioned", "rejected"})

# The case lifecycle from the plan; "received -> investigating" is the single-agent shortcut.
TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"planning", "investigating", "needs_review"}),
    "planning": frozenset({"investigating", "needs_review"}),
    "investigating": frozenset({"verifying", "needs_review"}),
    "verifying": frozenset({"closed_no_action", "needs_review", "awaiting_approval"}),
    "needs_review": frozenset({"awaiting_approval", "closed_no_action"}),
    "awaiting_approval": frozenset({"actioned", "rejected"}),
    "closed_no_action": frozenset(),
    "actioned": frozenset(),
    "rejected": frozenset(),
}


class InvalidTransition(ValueError):
    """The case cannot move from its current status to the requested one."""


def needs_approval(kind: str) -> bool:
    return ACTION_TIERS[kind] >= 2


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(f"a case cannot move from {current} to {target}")


def execution_refusal(action: dict[str, Any]) -> str | None:
    """Why this action must not execute now, or None when it may."""
    status = action["status"]
    if status in ("executed", "refused", "rejected"):
        return f"action is already {status}"
    if action["tier"] >= 2 and status != "approved":
        return f"tier {action['tier']} actions need a recorded human approval"
    return None
