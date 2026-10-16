import pytest

from lattice.cases.policy import (
    ACTION_TIERS,
    TERMINAL_STATES,
    InvalidTransition,
    check_transition,
    execution_refusal,
    needs_approval,
)


def test_tiers_follow_the_action_kind():
    assert ACTION_TIERS == {"annotate": 1, "escalate": 2, "draft_report": 2, "freeze": 3}
    assert not needs_approval("annotate")
    assert all(needs_approval(k) for k in ("escalate", "draft_report", "freeze"))


@pytest.mark.parametrize(
    ("kind", "status", "refused"),
    [
        ("annotate", "proposed", False),   # tier 1 runs automatically
        ("freeze", "proposed", True),      # tier 3 without approval
        ("escalate", "proposed", True),    # tier 2 without approval
        ("freeze", "approved", False),
        ("freeze", "rejected", True),
        ("freeze", "executed", True),      # never twice
        ("annotate", "executed", True),
    ],
)
def test_execution_needs_an_approval_for_tier_two_and_three(kind, status, refused):
    reason = execution_refusal({"kind": kind, "tier": ACTION_TIERS[kind], "status": status})

    assert (reason is not None) == refused


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("received", "planning"),
        ("received", "investigating"),  # single-agent mode skips planning
        ("investigating", "verifying"),
        ("verifying", "awaiting_approval"),
        ("verifying", "closed_no_action"),
        ("needs_review", "awaiting_approval"),
        ("needs_review", "closed_no_action"),
        ("awaiting_approval", "actioned"),
        ("awaiting_approval", "rejected"),
    ],
)
def test_lifecycle_transitions_from_the_plan_are_allowed(current, target):
    check_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("received", "actioned"),
        ("closed_no_action", "investigating"),
        ("actioned", "awaiting_approval"),
        ("needs_review", "actioned"),
    ],
)
def test_other_transitions_are_refused(current, target):
    with pytest.raises(InvalidTransition):
        check_transition(current, target)


def test_terminal_states_end_a_case():
    assert {"closed_no_action", "actioned", "rejected"} == TERMINAL_STATES
