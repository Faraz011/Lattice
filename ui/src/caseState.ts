// One view of a case, built by folding its events. Live mode overlays the API's case record
// (authoritative for status and results); replay mode uses the events alone.
import type {
  Action, ActionStatus, CaseEvent, CaseRecord, CaseStatus, CircuitReport, Evidence, Finding,
  Narrative, Verdict,
} from './types'

export interface ToolCall {
  tool: string
  resultId?: string
  args?: Record<string, unknown>
}

export interface Lane {
  hypothesis: string
  state: 'waiting' | 'running' | 'done'
  calls: ToolCall[]
  finding?: Finding
}

export interface CaseView {
  status: CaseStatus | null
  statusReason: string | null
  lanes: Lane[]
  results: string[]
  outcome: CaseStatus | null
  verdict: Verdict | null
  report: CircuitReport | null
  narrative: Narrative | null
  actions: Action[]
  review: { status: string; by: string } | null
}

export const EMPTY_VIEW: CaseView = {
  status: null, statusReason: null, lanes: [], results: [], outcome: null, verdict: null,
  report: null, narrative: null, actions: [], review: null,
}

function lane(view: CaseView, hypothesis: string): [Lane[], Lane] {
  const existing = view.lanes.find((l) => l.hypothesis === hypothesis)
  const current = existing ?? { hypothesis, state: 'waiting' as const, calls: [] }
  const lanes = existing ? view.lanes : [...view.lanes, current]
  return [lanes, current]
}

function withLane(view: CaseView, hypothesis: string, change: (l: Lane) => Lane): CaseView {
  const [lanes, current] = lane(view, hypothesis)
  return { ...view, lanes: lanes.map((l) => (l === current ? change(l) : l)) }
}

function withAction(view: CaseView, id: string, change: Partial<Action>): CaseView {
  const found = view.actions.find((a) => a.id === id)
  if (!found) return { ...view, actions: [...view.actions, { id, ...change } as Action] }
  return { ...view, actions: view.actions.map((a) => (a.id === id ? { ...a, ...change } : a)) }
}

export function reduce(view: CaseView, event: CaseEvent): CaseView {
  const d = event.data as Record<string, any>
  switch (event.type) {
    case 'case_started':
      return { ...view, status: 'received' }
    case 'hypotheses_chosen': {
      let next: CaseView = { ...view, status: 'investigating' }
      for (const h of d.hypotheses as string[]) next = withLane(next, h, (l) => l)
      return next
    }
    case 'investigation_started':
      return withLane({ ...view, status: 'investigating' }, d.hypothesis,
        (l) => ({ ...l, state: 'running' }))
    case 'tool_called':
      return withLane(view, d.hypothesis, (l) => ({
        ...l, state: 'running', calls: [...l.calls, { tool: d.tool, args: d.args }],
      }))
    case 'tool_result': {
      const resultId: string | undefined = d.result_id ?? undefined
      const next = withLane(view, d.hypothesis, (l) => {
        const calls = [...l.calls]
        const open = calls.findLastIndex((c) => c.tool === d.tool && !c.resultId)
        if (open >= 0) calls[open] = { ...calls[open], resultId }
        else calls.push({ tool: d.tool, resultId })
        return { ...l, calls }
      })
      return resultId ? { ...next, results: [...next.results, resultId] } : next
    }
    case 'finding':
      return withLane(view, d.hypothesis, (l) => ({ ...l, state: 'done', finding: d.finding }))
    case 'verification_started':
      return { ...view, status: 'verifying' }
    case 'verdict':
      return {
        ...view, status: d.outcome, outcome: d.outcome, verdict: d.verdict,
        report: d.circuit ?? null, narrative: d.narrative ?? null,
        statusReason: d.verdict?.review_reason ?? null,
      }
    case 'action_proposed':
      return withAction(view, d.action_id, {
        case_id: event.case_id, kind: d.kind, tier: d.tier, target_id: d.target_id,
        blast_radius: d.blast_radius, status: 'proposed',
      })
    case 'action_approved':
      return withAction(view, d.action_id, { status: 'approved', approved_by: d.by })
    case 'action_executed':
      return withAction({ ...view, status: 'actioned' }, d.action_id,
        { status: 'executed', outcome: d.outcome })
    case 'action_rejected':
      return withAction({ ...view, status: 'rejected', statusReason: d.reason }, d.action_id,
        { status: 'rejected', rejected_by: d.by, rejection_reason: d.reason })
    case 'action_refused':
      return withAction(view, d.action_id, { status: 'refused', refusal_reason: d.reason })
    case 'review_decision':
      return { ...view, status: d.status, review: { status: d.status, by: d.by } }
    default:
      return view
  }
}

export function fold(events: CaseEvent[]): CaseView {
  return events.reduce(reduce, EMPTY_VIEW)
}

/** Live mode: the case record and stored actions win where they have a value. */
export function overlay(view: CaseView, record: CaseRecord | null, actions: Action[]): CaseView {
  if (!record) return view
  let lanes = view.lanes
  for (const finding of record.findings ?? []) {
    if (!lanes.some((l) => l.hypothesis === finding.hypothesis && l.finding)) {
      lanes = [...lanes.filter((l) => l.hypothesis !== finding.hypothesis),
        { hypothesis: finding.hypothesis, state: 'done', calls: [], finding }]
    }
  }
  const merged = [...view.actions]
  for (const stored of actions) {
    const i = merged.findIndex((a) => a.id === stored.id)
    if (i >= 0) merged[i] = { ...merged[i], ...stored }
    else merged.push(stored)
  }
  return {
    ...view,
    lanes,
    status: record.status,
    statusReason: record.status_reason ?? view.statusReason,
    verdict: record.verdict ?? view.verdict,
    report: record.circuit ?? view.report,
    narrative: record.narrative ?? view.narrative,
    actions: merged,
  }
}

/** Replay mode: only edges that a tool call seen so far had returned. */
export function evidenceSoFar(evidence: Evidence, results: string[], seed?: string): Evidence {
  const seen = new Set(results)
  const edges = evidence.edges.filter((e) => e.sources.some((s) => seen.has(s)))
  const ends = new Set(edges.flatMap((e) => [e.src, e.dst]))
  const nodes = evidence.nodes.filter((n) => n.id === seed || ends.has(n.id))
  return { ...evidence, edges, nodes }
}

export function currentAction(view: CaseView): Action | null {
  const open: ActionStatus[] = ['proposed', 'approved']
  return view.actions.find((a) => open.includes(a.status)) ?? view.actions.at(-1) ?? null
}

export function incomplete(view: CaseView): Finding[] {
  return view.lanes.flatMap((l) => (l.finding && l.finding.status !== 'complete'
    ? [l.finding] : []))
}
