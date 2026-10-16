"""Typed handoffs between roles (KTD11): briefs in, findings and verdicts out.

Models produce the `*Report` shapes. The system wraps them with status fields the model never
sets, so a partial or failed run is still a well-typed value downstream.
"""

from typing import Literal

from pydantic import BaseModel, Field

# The fixed typology catalog (KTD7); "open" asks an investigator to consider all of them.
Typology = Literal[
    "peeling_chain",
    "fan_in_structuring",
    "fan_out",
    "round_trip",
    "rapid_layering",
    "shared_device",
    "exit_via_mixer",
]
Hypothesis = Typology | Literal["open"]
RunStatus = Literal["complete", "partial", "failed"]


class HypothesisBrief(BaseModel):
    case_id: str
    alert_id: str
    seed_account_id: str
    alert_reason: str
    hypothesis: Hypothesis


class Claim(BaseModel):
    statement: str = Field(description="One factual sentence about the graph.")
    rel_ids: list[str] = Field(default_factory=list,
                               description="Relationship IDs (e.g. tx_...) that show it.")
    node_ids: list[str] = Field(default_factory=list,
                                description="Node IDs (e.g. acct_...) that show it.")
    result_ids: list[str] = Field(description="result_id of each tool call the IDs came from.")


class FindingReport(BaseModel):
    """What an investigator model returns for one hypothesis."""

    hypothesis: Hypothesis
    verdict: Literal["supports", "refutes", "inconclusive"]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(description="Two or three sentences, no IDs needed.")
    claims: list[Claim] = Field(description="Every factual claim, each with its evidence IDs.")


class Finding(FindingReport):
    status: RunStatus = "complete"
    status_reason: str | None = None

    @classmethod
    def partial(cls, hypothesis: str, reason: str, status: RunStatus = "partial") -> "Finding":
        return cls(hypothesis=hypothesis, verdict="inconclusive", confidence=0.0,
                   summary=f"Investigation stopped early: {reason}.", claims=[],
                   status=status, status_reason=reason)

    @classmethod
    def from_report(cls, report: FindingReport) -> "Finding":
        return cls(**report.model_dump())

    def evidence_rel_ids(self) -> list[str]:
        return list(dict.fromkeys(r for c in self.claims for r in c.rel_ids))


class ActionProposal(BaseModel):
    kind: Literal["annotate", "escalate", "draft_report", "freeze"]
    target_id: str
    rationale: str
    tier: int


class Verdict(BaseModel):
    """The verifier's case-level decision.

    `suspicious`, `typology` and `risk` come from the risk scorer, the system of record for the
    decision (KTD7). `investigator_typology` records what the agents concluded, so a
    disagreement between the two stays visible (R15).
    """

    case_id: str
    suspicious: bool
    typology: Typology | None
    investigator_typology: Typology | None = None
    risk: Literal["low", "medium", "high"]
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    claims: list[Claim] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)
    unverified_ids: list[str] = Field(default_factory=list)
    needs_review: bool = False
    review_reason: str | None = None
    notes: list[str] = Field(default_factory=list)
