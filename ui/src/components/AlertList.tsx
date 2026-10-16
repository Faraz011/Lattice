// The alert queue: start an investigation, reopen one, or replay a recorded one.
import { shortId } from '../ids'
import type { Alert, CaseStatus } from '../types'

const STATUS_WORDS: Record<CaseStatus, string> = {
  received: 'Starting',
  planning: 'Planning',
  investigating: 'Investigating',
  verifying: 'Verifying',
  needs_review: 'Needs review',
  awaiting_approval: 'Awaiting approval',
  closed_no_action: 'Closed, no action',
  actioned: 'Action taken',
  rejected: 'Action rejected',
}

interface Props {
  alerts: Alert[] | null
  error: string | null
  selectedCase: string | null
  starting: string | null
  onInvestigate: (alert: Alert) => void
  onOpen: (caseId: string) => void
  onReplay: (caseId: string) => void
}

export function AlertList(
  { alerts, error, selectedCase, starting, onInvestigate, onOpen, onReplay }: Props,
) {
  if (error) {
    return <p className="error" role="alert">Alerts could not be loaded: {error}. Check that
      the API is running on its configured address.</p>
  }
  if (!alerts) return <p className="muted">Loading alerts.</p>
  if (alerts.length === 0) {
    return <p className="muted">No alerts yet. Load a world with the data generator to create
      some.</p>
  }
  return (
    <ul className="alerts">
      {alerts.map((alert) => {
        const open = alert.case_id && alert.case_id === selectedCase
        return (
          <li key={alert.id} className={open ? 'alert selected' : 'alert'}>
            <p className="alert-reason">{alert.reason}</p>
            <p className="alert-meta">
              <span title={alert.seed_account_id}>{shortId(alert.seed_account_id)}</span>
              {alert.ts && <span>{new Date(alert.ts).toLocaleDateString()}</span>}
              {alert.case_status && (
                <span className={`status status-${alert.case_status}`}>
                  {STATUS_WORDS[alert.case_status]}
                </span>
              )}
            </p>
            <div className="alert-actions">
              {alert.case_id ? (
                <button type="button" onClick={() => onOpen(alert.case_id!)}>Open case</button>
              ) : (
                <button type="button" className="primary" disabled={starting === alert.id}
                  onClick={() => onInvestigate(alert)}>
                  {starting === alert.id ? 'Starting' : 'Investigate'}
                </button>
              )}
              {alert.case_id && ['closed_no_action', 'actioned', 'rejected']
                .includes(alert.case_status ?? '') && (
                <button type="button" onClick={() => onInvestigate(alert)}>Investigate again</button>
              )}
              {alert.recorded_case_id && (
                <button type="button" onClick={() => onReplay(alert.recorded_case_id!)}>
                  Replay
                </button>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
