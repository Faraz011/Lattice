// The scorer's verdict: what pattern, how strong, and how firmly the evidence pins it down.
import { typologyName } from '../ids'
import type { CaseStatus, CircuitReport, Verdict } from '../types'

interface Props {
  verdict: Verdict
  report: CircuitReport | null
  outcome: CaseStatus | null
  reason?: string | null
}

const HEADLINES: Partial<Record<CaseStatus, string>> = {
  awaiting_approval: 'Suspicious activity found',
  needs_review: 'The evidence needs a person to decide',
  closed_no_action: 'No suspicious pattern found',
  actioned: 'Suspicious activity found',
  rejected: 'Suspicious activity found',
}

export function VerdictCard({ verdict, report, outcome, reason }: Props) {
  const circuit = report?.circuit
  const headline = (outcome && HEADLINES[outcome])
    ?? (verdict.suspicious ? 'Suspicious activity found' : 'No suspicious pattern found')
  const disagree = Boolean(verdict.investigator_typology
    && verdict.investigator_typology !== verdict.typology)
  const edges = circuit?.circuit_edges.length ?? 0
  return (
    <section className={`verdict risk-${verdict.risk}`} aria-labelledby="verdict-title">
      <h2 id="verdict-title">{headline}</h2>
      <p className="verdict-line">
        <span className="score">{verdict.score.toFixed(2)}</span>
        <span>
          {typologyName(verdict.typology)}, {verdict.risk} risk
          {circuit && <> (flagging threshold {circuit.threshold.toFixed(2)})</>}
        </span>
      </p>

      {outcome === 'closed_no_action' && (
        <p>Closed without action: {reason || 'the cited evidence scored below the threshold'}.</p>
      )}

      {(outcome === 'needs_review' || disagree) && (
        <dl className="two-verdicts">
          <dt>Risk scorer</dt><dd>{typologyName(verdict.typology)}</dd>
          <dt>Investigators</dt><dd>{typologyName(verdict.investigator_typology)}</dd>
          {verdict.review_reason && <><dt>Why review</dt><dd>{verdict.review_reason}</dd></>}
        </dl>
      )}

      {circuit?.status === 'circuit' && (
        <p className="circuit-line">
          The proof is {edges} {edges === 1 ? 'edge' : 'edges'}, numbered on the graph. On
          their own they score {circuit.sufficiency_score.toFixed(2)}; without them the rest
          scores {circuit.remaining_score.toFixed(2)}. In all, {circuit.supporting_edges.length}{' '}
          edges support the pattern.
        </p>
      )}
      {circuit?.redundant && (
        <p className="flag">There is a second, independent body of evidence: the rest still
          scores above the threshold without the circuit.</p>
      )}
      {verdict.rejected_citations.length + verdict.unverified_ids.length > 0 && (
        <p className="muted">
          {verdict.rejected_citations.length} citations were dropped because no tool call
          returned them; {verdict.unverified_ids.length} no longer exist in the graph.
        </p>
      )}
    </section>
  )
}
