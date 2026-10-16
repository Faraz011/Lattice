"""Action tiers (R16). Tier 0-1 run automatically; tier 2-3 need a human approval."""

from typing import Literal

ActionKind = Literal["annotate", "escalate", "draft_report", "freeze"]

ACTION_TIERS: dict[str, int] = {
    "annotate": 1,
    "escalate": 2,
    "draft_report": 2,
    "freeze": 3,
}


def needs_approval(kind: str) -> bool:
    return ACTION_TIERS[kind] >= 2
