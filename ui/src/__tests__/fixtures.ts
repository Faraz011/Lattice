import type { Action, CircuitReport, Evidence, Verdict } from '../types'

export const report: CircuitReport = {
  circuit: {
    status: 'circuit', threshold: 0.6, full_score: 0.82, typology: 'peeling_chain',
    detectors: { peeling_chain: 0.9 },
    circuit_edges: ['tx_b2', 'tx_a1'],
    supporting_edges: ['tx_a1', 'tx_b2', 'tx_c3'],
    sufficiency_score: 0.71, remaining_score: 0.12, comprehensive: true, redundant: false,
    attribution: { tx_a1: 0.4, tx_b2: 0.35, tx_c3: 0.1, tx_noise: 0 },
  },
  counterfactuals: {
    counterfactuals: [{ removed: ['tx_a1'], score_after: 0.41, typology_after: null }],
    note: null,
  },
  reasons: { peeling_chain: 'a chain of three hops, each skimming about 4%' },
  edges: [
    { id: 'tx_a1', kind: 'transfer', src: 'acct_seed', dst: 'acct_two', amount: 9000,
      ts: '2026-09-01T10:00:00' },
    { id: 'tx_b2', kind: 'transfer', src: 'acct_two', dst: 'acct_three', amount: 8600,
      ts: '2026-09-01T12:00:00' },
    { id: 'tx_c3', kind: 'transfer', src: 'acct_three', dst: 'acct_four', amount: 8200,
      ts: '2026-09-01T14:00:00' },
  ],
}

export const evidence: Evidence = {
  nodes: [
    { id: 'acct_seed', kind: 'account', account_kind: 'person', customer_id: 'cust_1' },
    { id: 'acct_two', kind: 'account', account_kind: 'person', customer_id: 'cust_2' },
    { id: 'acct_three', kind: 'account', account_kind: 'person', customer_id: 'cust_3' },
    { id: 'acct_four', kind: 'account', account_kind: 'mixer', customer_id: 'cust_4' },
    { id: 'acct_noise', kind: 'account', account_kind: 'person', customer_id: 'cust_5' },
  ],
  edges: [
    { ...report.edges[0], sources: ['led_first'] },
    { ...report.edges[1], sources: ['led_first', 'led_second'] },
    { ...report.edges[2], sources: ['led_second'] },
    { id: 'tx_noise', kind: 'transfer', src: 'acct_seed', dst: 'acct_noise', amount: 40,
      ts: '2026-09-02T09:00:00', sources: ['led_second'] },
  ],
  ledger: {
    led_first: { result_id: 'led_first', tool: 'graph_neighbors',
      params: { account_id: 'acct_seed' }, ts: '2026-10-16T10:00:00' },
    led_second: { result_id: 'led_second', tool: 'graph_match_pattern',
      params: { pattern: 'peeling_chain' }, ts: '2026-10-16T10:00:05' },
  },
  truncated: false,
}

export const verdict: Verdict = {
  case_id: 'case_1', suspicious: true, typology: 'peeling_chain',
  investigator_typology: 'peeling_chain', risk: 'high', score: 0.82, confidence: 0.8,
  claims: [], rejected_citations: [], unverified_ids: [], needs_review: false,
  review_reason: null, notes: [],
}

export const freeze: Action = {
  id: 'act_1', case_id: 'case_1', kind: 'freeze', tier: 3, target_id: 'acct_seed',
  status: 'proposed', rationale: 'peeling chain, risk high',
  blast_radius: { hops: 2, account_count: 14, customer_count: 9 },
}
