// The human gate (R16, R17): approve or reject a proposed action, with its blast radius in view.
// The approver token is typed in at runtime and kept for this tab only.
import { useState } from 'react'

import { ApiError, type Approver } from '../api'
import { shortId } from '../ids'
import type { Action } from '../types'

const TOKEN_KEY = 'lattice.approver'

function readStored(): Approver {
  try {
    const raw = window.sessionStorage.getItem(TOKEN_KEY)
    if (raw) return JSON.parse(raw) as Approver
  } catch {
    // storage unavailable: the token lives in memory only
  }
  return { token: '', name: '' }
}

export function useApprover(): [Approver, (next: Approver) => void] {
  const [approver, setApprover] = useState<Approver>(readStored)
  const update = (next: Approver) => {
    setApprover(next)
    try {
      window.sessionStorage.setItem(TOKEN_KEY, JSON.stringify(next))
    } catch {
      // keep it in memory
    }
  }
  return [approver, update]
}

export function ApproverFields({ approver, onChange }: {
  approver: Approver
  onChange: (next: Approver) => void
}) {
  return (
    <div className="approver">
      <label>
        Your name
        <input value={approver.name} autoComplete="name"
          onChange={(e) => onChange({ ...approver, name: e.target.value })} />
      </label>
      <label>
        Approver token
        <input type="password" value={approver.token} autoComplete="off"
          onChange={(e) => onChange({ ...approver, token: e.target.value })} />
      </label>
    </div>
  )
}

export function explain(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'That approver token was not accepted. Check it and try again.'
    if (error.status === 409) return `This action can no longer change: ${error.message}.`
    return error.message
  }
  return 'The server could not be reached. Check that the API is running, then try again.'
}

const VERBS: Record<Action['kind'], string> = {
  freeze: 'Freeze account',
  escalate: 'Escalate case',
  draft_report: 'Draft report',
  annotate: 'Add note',
}

interface Props {
  action: Action
  approver: Approver
  onApproverChange: (next: Approver) => void
  onApprove: () => Promise<unknown>
  onReject: (reason: string) => Promise<unknown>
  readOnly?: boolean
}

export function ApprovalPanel(
  { action, approver, onApproverChange, onApprove, onReject, readOnly = false }: Props,
) {
  const [busy, setBusy] = useState<'approving' | 'rejecting' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reviewed, setReviewed] = useState(false)
  const [reason, setReason] = useState('')

  const radius = action.blast_radius
  const gated = action.tier >= 2
  const verb = VERBS[action.kind] ?? action.kind

  const run = async (kind: 'approving' | 'rejecting', call: () => Promise<unknown>) => {
    setBusy(kind)
    setError(null)
    try {
      await call()
    } catch (e) {
      setError(explain(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className={`approval approval-${action.status}`} aria-labelledby="approval-title">
      <h3 id="approval-title">
        {action.status === 'proposed' ? `Proposed: ${verb.toLowerCase()}` : verb}
      </h3>
      <p>
        Target <span title={action.target_id}>{shortId(action.target_id)}</span>, tier{' '}
        {action.tier}{gated ? ', needs approval' : ''}.
      </p>
      {action.rationale && <p className="muted">{action.rationale}</p>}

      {radius ? (
        <p className="blast">
          Within {radius.hops} hops this reaches <strong>{radius.account_count} accounts</strong>{' '}
          held by <strong>{radius.customer_count} customers</strong>.
        </p>
      ) : (
        gated && <p className="muted">Waiting for the blast radius before approval.</p>
      )}

      {action.status === 'proposed' && readOnly && (
        <p className="state" role="status">Waiting for an approver. Decisions are turned off
          in a replay.</p>
      )}

      {action.status === 'proposed' && !readOnly && (
        <form onSubmit={(e) => { e.preventDefault(); void run('approving', onApprove) }}>
          <ApproverFields approver={approver} onChange={onApproverChange} />
          {gated && radius && (
            <label className="check">
              <input type="checkbox" checked={reviewed}
                onChange={(e) => setReviewed(e.target.checked)} />
              I have reviewed the blast radius
            </label>
          )}
          {error && <p className="error" role="alert">{error}</p>}
          <div className="buttons">
            <button type="submit" className={action.kind === 'freeze' ? 'primary seal' : 'primary'}
              disabled={busy !== null || !approver.token || (gated && (!radius || !reviewed))}>
              {busy === 'approving' ? 'Approving' : verb}
            </button>
          </div>
          <label className="reason">
            Reason for rejecting
            <input value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="Optional" />
          </label>
          <div className="buttons">
            <button type="button" disabled={busy !== null || !approver.token}
              onClick={() => void run('rejecting',
                () => onReject(reason || 'rejected by approver'))}>
              {busy === 'rejecting' ? 'Rejecting' : 'Reject'}
            </button>
          </div>
        </form>
      )}

      {action.status === 'approved' && (
        <p className="state" role="status">
          Approved by {action.approved_by ?? 'an approver'}. Executing.
        </p>
      )}
      {action.status === 'executed' && (
        <p className="state done" role="status">Done: {action.outcome}.</p>
      )}
      {action.status === 'rejected' && (
        <p className="state" role="status">
          Rejected by {action.rejected_by ?? 'an approver'}: {action.rejection_reason}.
        </p>
      )}
      {action.status === 'refused' && (
        <p className="state error" role="status">
          The executor refused this action: {action.refusal_reason}.
        </p>
      )}
    </section>
  )
}

export function ReviewPanel({ approver, onApproverChange, onEscalate, onClear }: {
  approver: Approver
  onApproverChange: (next: Approver) => void
  onEscalate: () => Promise<unknown>
  onClear: () => Promise<unknown>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = async (call: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await call()
    } catch (e) {
      setError(explain(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="approval" aria-labelledby="review-title">
      <h3 id="review-title">Your decision</h3>
      <p>Escalate to send the case for approval, or clear it to close it without action.</p>
      <ApproverFields approver={approver} onChange={onApproverChange} />
      {error && <p className="error" role="alert">{error}</p>}
      <div className="buttons">
        <button type="button" className="primary" disabled={busy || !approver.token}
          onClick={() => void run(onEscalate)}>Escalate</button>
        <button type="button" disabled={busy || !approver.token}
          onClick={() => void run(onClear)}>Clear case</button>
      </div>
    </section>
  )
}
