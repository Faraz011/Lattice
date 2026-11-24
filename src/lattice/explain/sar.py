"""A suspicious activity report (SAR) draft built only from the circuit report.

Every fact in it comes from the report: the scorer's typology and score, the circuit's transfers
(each returned by a ledgered tool call and re-verified), the backup routes, the inferred roles
and the counterfactuals. It is a deterministic template, so nothing in it can be invented.
Filing is simulated; an analyst reviews and edits the draft.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lattice.explain.report import CircuitReport

ROLE_ORDER = ("originator", "mule", "collector")


def _money(amount: float | None) -> str:
    return f"{amount:,.2f}" if amount is not None else "amount unknown"


def _when(ts: str | None) -> str:
    return ts[:16].replace("T", " ") if ts else "time unknown"


def sar_draft(report: "CircuitReport", subject: str) -> str:
    circuit = report.circuit
    edges = {e.id: e for e in report.edges}
    typology = (circuit.typology or "unclassified").replace("_", " ")
    lines = [
        "SUSPICIOUS ACTIVITY REPORT: DRAFT FOR ANALYST REVIEW (simulated filing)",
        "",
        f"Subject account: {subject}",
        f"Activity: {typology}. Risk score {circuit.full_score:.2f} against a reporting threshold "
        f"of {circuit.threshold:.2f}.",
        "",
        f"Evidence ({len(circuit.circuit_edges)} transfers that on their own keep the score above "
        "the threshold):",
    ]
    route = report.routes[0].edges if report.routes else circuit.circuit_edges
    for edge_id in route:
        e = edges.get(edge_id)
        if e is None:
            continue
        if e.kind == "transfer":
            lines.append(f"  - {_when(e.ts)}  {e.src} -> {e.dst}  {_money(e.amount)}  [{e.id}]")
        else:
            lines.append(f"  - {e.src} used device {e.dst}  [{e.id}]")

    if len(report.routes) > 1:
        lines += ["", "Further routes. The same activity continues without the evidence above:"]
        for n, backup in enumerate(report.routes[1:], start=2):
            path = " -> ".join(backup.accounts)
            lines.append(f"  - Route {n} ({len(backup.path)} transfers; {len(backup.edges)} of "
                         f"them score {backup.score:.2f} on their own): {path}")
        if report.route_relation:
            lines.append(f"  The routes are {report.route_relation}.")
        lines.append("  Restricting a single account on the first route would not stop the "
                     "activity; see the freeze assessments below.")

    if report.roles:
        lines += ["", "Roles inferred from the flow of funds:"]
        for role in ROLE_ORDER:
            members = sorted(a for a, r in report.roles.items() if r == role)
            if members:
                lines.append(f"  - {role}: {', '.join(members)}")

    essential = [w for w in report.freeze_whatifs if not w.still_flagged]
    resilient = [w for w in report.freeze_whatifs if w.still_flagged]
    if report.freeze_whatifs:
        lines += ["", "Freeze assessments (effect on this evidence of restricting one account):"]
        if essential:
            lines.append("  - Would stop the activity: " + ", ".join(
                f"{w.account_id} (score falls to {w.score_after:.2f})" for w in essential))
        if resilient:
            lines.append("  - Would not stop it, as another route remains: " + ", ".join(
                w.account_id for w in resilient))

    cfs = report.counterfactuals.counterfactuals
    lines += ["", "What would change this assessment:"]
    if cfs:
        best = cfs[0]
        lines.append(f"  - Without {' and '.join(best.removed)} the score would be "
                     f"{best.score_after:.2f}, below the threshold.")
    else:
        lines.append("  - No removal of one or two transfers brings the score below the "
                     "threshold.")
    lines += [
        "",
        "Method: each transfer cited above was returned by a recorded tool call in this case's "
        "evidence ledger and re-checked against the graph before scoring. The score comes from "
        "deterministic typology detectors, not from a language model.",
    ]
    return "\n".join(lines) + "\n"
