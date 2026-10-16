import { describe, expect, it } from 'vitest'

import { currentAction, evidenceSoFar, fold, incomplete, overlay } from '../caseState'
import type { CaseEvent, CaseRecord } from '../types'
import { evidence, freeze, report, verdict } from './fixtures'

let n = 0
const ev = (type: string, data: Record<string, unknown> = {}): CaseEvent => ({
  id: `${++n}-0`, case_id: 'case_1', type, data, ts: new Date(2026, 9, 16, 10, 0, n).toISOString(),
})

const investigation = [
  ev('case_started'),
  ev('hypotheses_chosen', { hypotheses: ['peeling_chain', 'fan_out'] }),
  ev('investigation_started', { hypothesis: 'peeling_chain' }),
  ev('tool_called', { hypothesis: 'peeling_chain', tool: 'graph_neighbors', args: {} }),
  ev('tool_result', { hypothesis: 'peeling_chain', tool: 'graph_neighbors',
    result_id: 'led_first' }),
]

describe('fold', () => {
  it('builds a lane per hypothesis and records each returned call', () => {
    const view = fold(investigation)

    expect(view.status).toBe('investigating')
    expect(view.lanes.map((l) => [l.hypothesis, l.state])).toEqual([
      ['peeling_chain', 'running'], ['fan_out', 'waiting']])
    expect(view.lanes[0].calls).toEqual([
      { tool: 'graph_neighbors', args: {}, resultId: 'led_first' }])
    expect(view.results).toEqual(['led_first'])
  })

  it('follows a case through verdict, proposal, approval and execution', () => {
    const view = fold([
      ...investigation,
      ev('finding', { hypothesis: 'fan_out', finding: { hypothesis: 'fan_out',
        verdict: 'refutes', status: 'partial', status_reason: 'step budget reached' } }),
      ev('verification_started'),
      ev('verdict', { outcome: 'awaiting_approval', verdict, circuit: report,
        narrative: { text: 't', source: 'template' } }),
      ev('action_proposed', { action_id: 'act_1', kind: 'freeze', tier: 3,
        target_id: 'acct_seed', blast_radius: freeze.blast_radius }),
      ev('action_approved', { action_id: 'act_1', by: 'sam' }),
      ev('action_executed', { action_id: 'act_1', outcome: 'frozen' }),
    ])

    expect(view.status).toBe('actioned')
    expect(view.report?.circuit.circuit_edges).toEqual(['tx_b2', 'tx_a1'])
    expect(currentAction(view)).toMatchObject({ status: 'executed', approved_by: 'sam',
      outcome: 'frozen' })
    expect(incomplete(view).map((f) => f.hypothesis)).toEqual(['fan_out'])
  })

  it('records a rejection and its reason', () => {
    const view = fold([
      ev('action_proposed', { action_id: 'act_1', kind: 'freeze', tier: 3, target_id: 'a' }),
      ev('action_rejected', { action_id: 'act_1', by: 'sam', reason: 'false positive' }),
    ])

    expect(view.status).toBe('rejected')
    expect(view.actions[0]).toMatchObject({ status: 'rejected', rejection_reason: 'false positive' })
  })
})

describe('overlay', () => {
  it('lets the stored case record decide status and results', () => {
    const record = { id: 'case_1', status: 'needs_review', verdict, circuit: report,
      findings: [{ hypothesis: 'open', verdict: 'supports', status: 'complete' }],
    } as unknown as CaseRecord

    const view = overlay(fold(investigation.slice(0, 1)), record, [freeze])

    expect(view.status).toBe('needs_review')
    expect(view.verdict).toBe(verdict)
    expect(view.lanes.map((l) => l.hypothesis)).toEqual(['open'])
    expect(view.actions).toEqual([freeze])
  })
})

describe('evidenceSoFar', () => {
  it('shows only edges a call seen so far returned, plus the seed', () => {
    const early = evidenceSoFar(evidence, ['led_first'], 'acct_seed')

    expect(early.edges.map((e) => e.id)).toEqual(['tx_a1', 'tx_b2'])
    expect(early.nodes.map((n) => n.id)).toEqual(['acct_seed', 'acct_two', 'acct_three'])
    expect(evidenceSoFar(evidence, [], 'acct_seed').nodes.map((n) => n.id))
      .toEqual(['acct_seed'])
  })
})
