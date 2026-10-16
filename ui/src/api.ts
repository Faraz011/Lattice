// The Lattice API client. The approver token is passed in per call from memory; it is never
// part of the build (no VITE_ variable holds it).
import type { Action, Alert, CaseEvent, CaseRecord, Evidence, Recording } from './types'

export const API_URL: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8080'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface Approver {
  token: string
  name: string
}

async function call<T>(path: string, init: RequestInit = {}, approver?: Approver): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (approver) {
    headers['X-Approver-Token'] = approver.token
    if (approver.name) headers['X-Approver-Name'] = approver.name
  }
  const response = await fetch(`${API_URL}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail = response.statusText
    try {
      detail = (await response.json()).detail ?? detail
    } catch {
      // the body was not JSON; keep the status text
    }
    throw new ApiError(response.status, String(detail))
  }
  return response.json() as Promise<T>
}

export const api = {
  alerts: () => call<{ alerts: Alert[] }>('/alerts').then((r) => r.alerts),
  investigate: (alertId: string, mode: 'single' | 'orchestrated') =>
    call<{ case: CaseRecord; created: boolean }>(`/alerts/${alertId}/investigate`, {
      method: 'POST', body: JSON.stringify({ mode }),
    }),
  getCase: (caseId: string) =>
    call<{ case: CaseRecord; actions: Action[] }>(`/cases/${caseId}`),
  evidence: (caseId: string) => call<Evidence>(`/cases/${caseId}/evidence`),
  recording: (caseId: string) => call<Recording>(`/cases/${caseId}/recording`),
  saveRecording: (caseId: string) =>
    call<Recording>(`/cases/${caseId}/recording`, { method: 'POST' }),
  approve: (actionId: string, approver: Approver) =>
    call<{ action: Action }>(`/actions/${actionId}/approve`, { method: 'POST' }, approver),
  reject: (actionId: string, approver: Approver, reason: string) =>
    call<{ action: Action }>(`/actions/${actionId}/reject`, {
      method: 'POST', body: JSON.stringify({ reason }),
    }, approver),
  escalate: (caseId: string, approver: Approver) =>
    call<{ case: CaseRecord }>(`/cases/${caseId}/escalate`, { method: 'POST' }, approver),
  clear: (caseId: string, approver: Approver) =>
    call<{ case: CaseRecord }>(`/cases/${caseId}/clear`, { method: 'POST' }, approver),
}

export type Connection = 'connecting' | 'live' | 'reconnecting'

/** Follow a case's events. EventSource reconnects by itself and resumes from Last-Event-ID. */
export function followEvents(
  caseId: string,
  onEvent: (event: CaseEvent) => void,
  onConnection: (state: Connection) => void,
): () => void {
  const source = new EventSource(`${API_URL}/cases/${caseId}/events`)
  onConnection('connecting')
  source.onopen = () => onConnection('live')
  source.onerror = () => onConnection('reconnecting')
  source.onmessage = null
  const listener = (message: MessageEvent) => onEvent(JSON.parse(message.data) as CaseEvent)
  for (const type of EVENT_TYPES) source.addEventListener(type, listener)
  return () => source.close()
}

// Named SSE events the API sends (the server sets `event:` to the event type).
export const EVENT_TYPES = [
  'case_started', 'hypotheses_chosen', 'investigation_started', 'tool_called', 'tool_result',
  'finding', 'verification_started', 'verdict', 'action_proposed', 'action_approved',
  'action_rejected', 'action_executed', 'action_refused', 'review_decision', 'echo',
]
