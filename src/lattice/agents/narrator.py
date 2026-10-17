"""The narrator (R14): explain the circuit report in prose, citing only IDs the report contains.

The model's text is checked by extracting every ID it mentions. One regeneration is allowed,
with the offending IDs named; after that, or when the model is unavailable, a deterministic
template built from the report is used instead. A verdict never waits on prose.
"""

import re
from typing import Literal

from pydantic import BaseModel
from pydantic_ai.models import Model

from lattice.agents.runtime import AgentRuntime
from lattice.explain.report import CircuitReport

ID_PATTERN = re.compile(
    r"\b(?:used_device|owns):[A-Za-z0-9_]+:[A-Za-z0-9_]+|"
    r"\b(?:tx|acct|cust|dev|alert|case|led|act|rec)_[A-Za-z0-9]+\b"
)
ATTEMPTS = 2


class Narrative(BaseModel):
    text: str
    source: Literal["model", "template"]


def mentioned_ids(text: str) -> set[str]:
    return set(ID_PATTERN.findall(text))


def allowed_ids(report: CircuitReport) -> set[str]:
    ids = set(report.circuit.circuit_edges)
    for edge in report.edges:
        ids |= {edge.id, edge.src, edge.dst}
    for cf in report.counterfactuals.counterfactuals:
        ids |= set(cf.removed)
    return ids


def describe(report: CircuitReport) -> str:
    """The report as compact text for the model."""
    c = report.circuit
    lines = [
        f"typology: {c.typology}",
        f"score: {c.full_score:.2f} (threshold {c.threshold:.2f})",
        f"detector reasons: {report.reasons}",
        f"circuit sufficiency score: {c.sufficiency_score:.2f}; "
        f"comprehensive: {c.comprehensive}; redundant evidence: {c.redundant}",
        "circuit edges, in time order:",
    ]
    by_id = {e.id: e for e in report.edges}
    for edge_id in c.circuit_edges:
        e = by_id[edge_id]
        detail = f"{e.amount:,.2f} at {e.ts}" if e.kind == "transfer" else "shares a device"
        lines.append(f"- {e.id}: {e.src} -> {e.dst}, {detail}")
    if report.counterfactuals.counterfactuals:
        lines.append("counterfactuals (removing these flips the verdict):")
        for cf in report.counterfactuals.counterfactuals:
            lines.append(f"- remove {', '.join(cf.removed)}: score becomes {cf.score_after:.2f}")
    else:
        lines.append(f"counterfactuals: {report.counterfactuals.note}")
    return "\n".join(lines)


def template_narrative(report: CircuitReport) -> str:
    c = report.circuit
    if c.status != "circuit":
        return (f"The risk score is {c.full_score:.2f}, below the {c.threshold:.2f} threshold, "
                "so no evidence circuit was drawn.")
    by_id = {e.id: e for e in report.edges}
    steps = []
    for edge_id in c.circuit_edges:
        e = by_id[edge_id]
        if e.kind == "transfer":
            amount = f", {e.amount:,.2f}" if e.amount is not None else ""
            steps.append(f"{e.id} ({e.src} to {e.dst}{amount})")
        else:
            steps.append(f"{e.id} (shared device)")
    parts = [
        f"Lattice flags this case as {c.typology} with a risk score of {c.full_score:.2f} "
        f"against a threshold of {c.threshold:.2f}.",
        f"The decision rests on {len(c.circuit_edges)} pieces of evidence, which on their own "
        f"score {c.sufficiency_score:.2f}: " + "; ".join(steps) + ".",
    ]
    cfs = report.counterfactuals.counterfactuals
    if cfs:
        best = cfs[0]
        parts.append(f"Without {' and '.join(best.removed)} the score would fall to "
                     f"{best.score_after:.2f}, below the threshold.")
    else:
        parts.append("No removal of one or two pieces of evidence changes the verdict; "
                     "the evidence is redundant.")
    if c.redundant:
        parts.append("Other cited evidence would still flag the case without this circuit.")
    return " ".join(parts)


async def narrate(
    runtime: AgentRuntime, case_id: str, report: CircuitReport, model: Model | None = None
) -> Narrative:
    if report.circuit.status != "circuit":
        return Narrative(text=template_narrative(report), source="template")
    allowed = allowed_ids(report)
    prompt = f"Circuit report:\n{describe(report)}\n\nExplain this case."
    for _ in range(ATTEMPTS):
        outcome = await runtime.run("narrator", case_id, prompt, str,
                                    lambda reason, status="partial": None, model=model,
                                    step_budget=2)
        if outcome.output is None:
            break
        foreign = mentioned_ids(outcome.output) - allowed
        if not foreign:
            return Narrative(text=outcome.output.strip(), source="model")
        prompt += (f"\n\nYour previous answer mentioned IDs that are not in the report: "
                   f"{', '.join(sorted(foreign))}. Use only IDs from the report.")
    return Narrative(text=template_narrative(report), source="template")
