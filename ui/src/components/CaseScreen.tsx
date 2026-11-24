// One case, laid out by stage: while agents work, the graph grows beside their lanes; once a
// verdict exists, the circuit, the explanation and the decision take the side panel.
import { useMemo, useState } from 'react'

import { api, type Connection } from '../api'
import { currentAction, incomplete } from '../caseState'
import { shortId, typologyName } from '../ids'
import type { CaseSession, ReplaySession } from '../useCase'
import { ApprovalPanel, ReviewPanel, useApprover } from './ApprovalPanel'
import { Counterfactuals } from './Counterfactuals'
import { ExplanationSize } from './ExplanationSize'
import { FreezeWhatIf } from './FreezeWhatIf'
import { GraphView } from './GraphView'
import { Inspector } from './Inspector'
import { LlmAttribution } from './LlmAttribution'
import { InvestigationTimeline, StageBar } from './InvestigationTimeline'
import { Narrative } from './Narrative'
import { RoutesPanel } from './RoutesPanel'
import { SarDraft } from './SarDraft'
import { VerdictCard } from './VerdictCard'

const CONNECTION_WORDS: Record<Connection, string> = {
  connecting: 'Connecting',
  live: 'Live',
  reconnecting: 'Reconnecting to the event stream',
}

const DECIDED = ['awaiting_approval', 'needs_review', 'closed_no_action', 'actioned', 'rejected']

// One way of looking at the evidence at a time, so overlays never fight on the graph.
type Lens =
  | { kind: 'none' }
  | { kind: 'counterfactual'; index: number }
  | { kind: 'freeze'; account: string }
  | { kind: 'size'; k: number }

const NONE: Lens = { kind: 'none' }

interface Props {
  session: CaseSession
  replay?: ReplaySession
  onChanged?: () => void
}

export function CaseScreen({ session, replay, onChanged }: Props) {
  const { view, record, evidence } = session
  const [selected, setSelected] = useState<string | null>(null)
  const [lens, setLens] = useState<Lens>(NONE)
  const [approver, setApprover] = useApprover()

  const report = view.report
  const whatif = lens.kind === 'freeze'
    ? report?.freeze_whatifs?.find((w) => w.account_id === lens.account) ?? null : null
  const removed = useMemo(() => {
    if (lens.kind === 'counterfactual' && report) {
      return new Set(report.counterfactuals.counterfactuals[lens.index]?.removed ?? [])
    }
    return new Set(whatif?.removed_edges ?? [])
  }, [lens, report, whatif])
  const proof = useMemo(() => (lens.kind === 'size' && report?.size_curve
    ? report.size_curve.ranked_edges.slice(0, lens.k) : undefined), [lens, report])
  const backup = whatif?.backup_edges

  const status = view.status ?? record?.status ?? null
  const decided = status != null && DECIDED.includes(status) && view.verdict != null
  const action = currentAction(view)
  const stopped = incomplete(view)
  const caseId = record?.id

  const after = async (call: Promise<unknown>) => {
    await call
    session.refresh()
    onChanged?.()
  }

  return (
    <div className="case">
      {replay && (
        <div className="replay-bar" role="region" aria-label="Replay controls">
          <span>
            Replaying a recorded investigation
            {replay.recordedAt && <> from {new Date(replay.recordedAt).toLocaleString()}</>}.
            Step {replay.position} of {replay.total}.
          </span>
          {replay.playing
            ? <button type="button" onClick={replay.pause}>Pause</button>
            : <button type="button" onClick={replay.play}>Play</button>}
          <button type="button" className="quiet" onClick={replay.restart}>Start over</button>
        </div>
      )}

      <header className="case-head">
        <div>
          <h1>{record?.alert_reason || 'Investigation'}</h1>
          <p className="case-meta">
            Seed account <span title={record?.seed_account_id}>
              {record ? shortId(record.seed_account_id) : ''}</span>
            {record && <>, {record.mode === 'orchestrated' ? 'one investigator per pattern'
              : 'one investigator'}</>}
          </p>
        </div>
        {!replay && (
          <p className={`connection connection-${session.connection}`} role="status">
            {CONNECTION_WORDS[session.connection]}
          </p>
        )}
      </header>
      <StageBar status={status} />
      {session.error && <p className="error" role="alert">{session.error}</p>}

      <div className="case-body">
        <div className="graph-area">
          <GraphView evidence={evidence} report={decided ? report : null}
            seed={record?.seed_account_id} removed={removed} proof={proof} backup={backup}
            frozen={whatif?.account_id ?? null} roles={decided ? report?.roles : undefined}
            focusId={selected} onSelect={setSelected} />
          {decided && report?.circuit.status === 'circuit' && (
            <p className="legend">
              <span className="key key-circuit">Numbered red edges: the circuit, the smallest set
                that alone keeps the verdict</span>
              <span className="key key-support">Dark: other edges the detectors used</span>
              <span className="key key-context">Faded: queried but not used</span>
              {backup && backup.length > 0 && (
                <span className="key key-backup">Dashed, B1, B2...: the route that still
                  proves the case after the freeze</span>
              )}
            </p>
          )}
          {evidence?.truncated && <p className="muted">Showing the first 600 edges found.</p>}
          {selected && (
            <Inspector id={selected} evidence={evidence} report={report}
              onClose={() => setSelected(null)} />
          )}
        </div>

        <div className="panel">
          {stopped.length > 0 && (
            <p className="banner" role="status">
              {stopped.map((f) => `${f.hypothesis === 'open' ? 'The investigator'
                : `The ${typologyName(f.hypothesis)} investigator`} stopped early: ${
                f.status_reason}.`).join(' ')} The verdict uses what was found before then.
            </p>
          )}

          {!decided && !record && !session.error && <p className="muted">Loading the case.</p>}
          {!decided && record && (
            <InvestigationTimeline lanes={view.lanes} verifying={status === 'verifying'} />
          )}

          {decided && view.verdict && (
            <>
              <VerdictCard verdict={view.verdict} report={report} outcome={status}
                reason={view.statusReason ?? record?.status_reason} />
              {view.narrative && <Narrative narrative={view.narrative} onFocus={setSelected} />}
              {report?.routes && report.routes.length > 0 && (
                <RoutesPanel routes={report.routes} roles={report.roles ?? {}}
                  relation={report.route_relation} onFocus={setSelected} />
              )}
              {report?.freeze_whatifs && report.freeze_whatifs.length > 0 && (
                <FreezeWhatIf whatifs={report.freeze_whatifs}
                  threshold={report.circuit.threshold}
                  active={lens.kind === 'freeze' ? lens.account : null}
                  onSelect={(account) => setLens(account ? { kind: 'freeze', account } : NONE)}
                  onFocus={setSelected} />
              )}
              {report?.size_curve && (
                <ExplanationSize curve={report.size_curve}
                  fullScore={report.circuit.full_score} threshold={report.circuit.threshold}
                  size={lens.kind === 'size' ? lens.k : null}
                  onSize={(k) => setLens(k == null ? NONE : { kind: 'size', k })} />
              )}
              {report?.circuit.status === 'circuit' && (
                <Counterfactuals report={report}
                  active={lens.kind === 'counterfactual' ? lens.index : null}
                  onToggle={(index) => setLens(index == null ? NONE
                    : { kind: 'counterfactual', index })} />
              )}
              {report?.llm_attribution && (
                <LlmAttribution attribution={report.llm_attribution} onFocus={setSelected} />
              )}
              {status === 'needs_review' && !replay && caseId && (
                <ReviewPanel approver={approver} onApproverChange={setApprover}
                  onEscalate={() => after(api.escalate(caseId, approver))}
                  onClear={() => after(api.clear(caseId, approver))} />
              )}
              {action && (
                <ApprovalPanel action={action} approver={approver} readOnly={Boolean(replay)}
                  onApproverChange={setApprover}
                  onApprove={() => after(api.approve(action.id, approver))}
                  onReject={(reason) => after(api.reject(action.id, approver, reason))} />
              )}
              {report?.sar_draft && <SarDraft text={report.sar_draft} />}
              {status === 'awaiting_approval' && !action && (
                <p className="muted">Escalated for approval. No action has been proposed for this
                  case yet.</p>
              )}
              <details className="history">
                <summary>How the agents got here</summary>
                <InvestigationTimeline lanes={view.lanes} verifying={false} />
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
