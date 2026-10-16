"""Combine findings and the risk score into a case outcome (R15, KTD11).

Hypotheses are alternatives, so the investigators' view is "suspicious" when any complete
finding supports its hypothesis. The scorer decides independently. When the two disagree, or
no investigator finished, a human reviews the case.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from lattice.agents.schemas import Claim, Finding, Verdict
from lattice.scoring.scorer import ScoreResult

HIGH_RISK = 0.85

OutcomeStatus = Literal["awaiting_approval", "needs_review", "closed_no_action"]


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    verdict: Verdict


def decide(
    case_id: str,
    findings: Sequence[Finding],
    score: ScoreResult,
    threshold: float,
    rejected_citations: Sequence[str],
    unverified_ids: Sequence[str],
    claims: Sequence[Claim] = (),
) -> Outcome:
    complete = [f for f in findings if f.status == "complete"]
    supported = sorted((f for f in complete if f.verdict == "supports"),
                       key=lambda f: (-f.confidence, f.hypothesis))
    investigators_suspicious = bool(supported)
    scorer_suspicious = score.score >= threshold

    notes = [f"{f.hypothesis} finding was {f.status}: {f.status_reason}"
             for f in findings if f.status != "complete"]
    if not complete:
        status: OutcomeStatus = "needs_review"
        reason = "no investigator finished; the evidence gathered so far needs a human"
    elif investigators_suspicious != scorer_suspicious:
        status = "needs_review"
        reason = (
            f"investigators and scorer disagree: investigators "
            f"{'support ' + supported[0].hypothesis if supported else 'found nothing'}, "
            f"scorer {score.score:.2f} vs threshold {threshold:.2f}"
        )
    elif scorer_suspicious:
        status, reason = "awaiting_approval", None
    else:
        status, reason = "closed_no_action", None

    investigator_typology = supported[0].hypothesis if supported else None
    verdict = Verdict(
        case_id=case_id,
        suspicious=scorer_suspicious,
        typology=score.typology if scorer_suspicious else None,
        investigator_typology=(
            investigator_typology if investigator_typology != "open" else score.typology
        ),
        risk="high" if score.score >= HIGH_RISK else "medium" if scorer_suspicious else "low",
        score=score.score,
        confidence=max((f.confidence for f in complete), default=0.0),
        claims=list(claims),
        rejected_citations=list(rejected_citations),
        unverified_ids=list(unverified_ids),
        needs_review=status == "needs_review",
        review_reason=reason,
        notes=notes,
    )
    return Outcome(status=status, verdict=verdict)
