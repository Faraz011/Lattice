"""Monitoring alerts: one per case, raised on a single seed account (R3).

The reason describes the surface shape a monitoring rule would see, so a decoy and the typology
it imitates raise identical alerts. Nothing in the alert reveals the answer.
"""

from lattice.datagen.builder import Pattern, WorldBuilder, hours
from lattice.graph.loader import Alert

REASONS = {
    "peeling_chain": "large inbound followed by rapid outbound transfers",
    "fan_in_structuring": "many inbound transfers in a short period",
    "fan_out": "many outbound transfers in a short period",
    "round_trip": "funds returned to originating account",
    "rapid_layering": "rapid movement of funds through new accounts",
    "shared_device": "device shared across multiple customers",
    "exit_via_mixer": "outbound transfer to high-risk counterparty",
    "payroll_fan_out": "many outbound transfers in a short period",
    "merchant_fan_in": "many inbound transfers in a short period",
    "family_cycle": "funds returned to originating account",
}


def raise_alert(b: WorldBuilder, pattern: Pattern) -> Alert:
    latest = max(b.transfer_by_id(t).ts for t in pattern.transfer_ids)
    alert = Alert(
        id=b.ids.next("alert"),
        seed_account_id=pattern.seed_account_id,
        reason=REASONS[pattern.kind],
        ts=latest + hours(1),
    )
    b.batch.alerts.append(alert)
    return alert
