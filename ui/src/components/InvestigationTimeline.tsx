// Where the case is in its lifecycle, and what each investigator is doing or found.
import type { Lane } from '../caseState'
import { typologyName } from '../ids'
import type { CaseStatus } from '../types'

const STEPS: Array<{ label: string; statuses: CaseStatus[] }> = [
  { label: 'Received', statuses: ['received', 'planning'] },
  { label: 'Investigating', statuses: ['investigating'] },
  { label: 'Verifying', statuses: ['verifying'] },
  { label: 'Decision', statuses: ['awaiting_approval', 'needs_review'] },
  { label: 'Closed', statuses: ['closed_no_action', 'actioned', 'rejected'] },
]

export function StageBar({ status }: { status: CaseStatus | null }) {
  const at = STEPS.findIndex((s) => status && s.statuses.includes(status))
  return (
    <ol className="stages" aria-label="Case progress">
      {STEPS.map((step, i) => (
        <li key={step.label} className={i < at ? 'past' : i === at ? 'now' : 'next'}
          aria-current={i === at ? 'step' : undefined}>
          {step.label}
        </li>
      ))}
    </ol>
  )
}

const VERDICT_WORDS = { supports: 'Supports', refutes: 'Refutes', inconclusive: 'Inconclusive' }

export function InvestigationTimeline({ lanes, verifying }: { lanes: Lane[]; verifying: boolean }) {
  if (lanes.length === 0) {
    return <p className="muted">Choosing which patterns to test.</p>
  }
  return (
    <div className="lanes">
      {lanes.map((lane) => (
        <section key={lane.hypothesis} className={`lane lane-${lane.state}`}>
          <header>
            <h3>{lane.hypothesis === 'open' ? 'Investigator' : typologyName(lane.hypothesis)}</h3>
            <span className="lane-state">
              {lane.finding ? VERDICT_WORDS[lane.finding.verdict]
                : lane.state === 'running' ? 'Querying' : 'Waiting'}
            </span>
          </header>
          {lane.calls.length > 0 && (
            <ol className="calls">
              {lane.calls.map((call, i) => (
                <li key={i} className={call.resultId ? 'returned' : 'pending'}>
                  {call.tool.replaceAll('_', ' ')}
                </li>
              ))}
            </ol>
          )}
          {lane.finding && (
            <p className="finding">
              {lane.finding.summary}
              {lane.finding.status !== 'complete' && (
                <span className="flag"> Stopped early: {lane.finding.status_reason}</span>
              )}
            </p>
          )}
        </section>
      ))}
      {verifying && (
        <section className="lane lane-running verifier">
          <header><h3>Verifier</h3><span className="lane-state">Checking citations</span></header>
          <p className="finding">Every cited edge is matched against the tool-call ledger, then
            the evidence is scored.</p>
        </section>
      )}
    </div>
  )
}
