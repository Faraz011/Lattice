// Shapes returned by the Lattice API. Field names follow the Python models.

export type CaseStatus =
  | 'received' | 'planning' | 'investigating' | 'verifying' | 'needs_review'
  | 'awaiting_approval' | 'closed_no_action' | 'actioned' | 'rejected'

export interface Alert {
  id: string
  seed_account_id: string
  reason: string
  ts: string | null
  case_id: string | null
  case_status: CaseStatus | null
  recorded_case_id: string | null
}

export interface Claim {
  statement: string
  rel_ids: string[]
  node_ids: string[]
  result_ids: string[]
}

export interface Finding {
  hypothesis: string
  verdict: 'supports' | 'refutes' | 'inconclusive'
  confidence: number
  summary: string
  claims: Claim[]
  status: 'complete' | 'partial' | 'failed'
  status_reason: string | null
}

export interface Verdict {
  case_id: string
  suspicious: boolean
  typology: string | null
  investigator_typology: string | null
  risk: 'low' | 'medium' | 'high'
  score: number
  confidence: number
  claims: Claim[]
  rejected_citations: string[]
  unverified_ids: string[]
  needs_review: boolean
  review_reason: string | null
  notes: string[]
}

export interface Circuit {
  status: 'circuit' | 'below_threshold'
  threshold: number
  full_score: number
  typology: string | null
  detectors: Record<string, number>
  circuit_edges: string[]
  supporting_edges: string[]
  sufficiency_score: number
  remaining_score: number
  comprehensive: boolean
  redundant: boolean
  attribution: Record<string, number>
}

export interface Counterfactual {
  removed: string[]
  score_after: number
  typology_after: string | null
}

export interface EdgeDetail {
  id: string
  kind: 'transfer' | 'device_link'
  src: string
  dst: string
  amount?: number | null
  ts?: string | null
}

export interface CircuitReport {
  circuit: Circuit
  counterfactuals: { counterfactuals: Counterfactual[]; note: string | null }
  reasons: Record<string, string>
  edges: EdgeDetail[]
}

export interface Narrative {
  text: string
  source: 'model' | 'template'
}

export interface BlastRadius {
  hops: number
  account_count: number
  customer_count: number
  sample_accounts?: string[]
}

export type ActionStatus = 'proposed' | 'approved' | 'executed' | 'rejected' | 'refused'

export interface Action {
  id: string
  case_id: string
  kind: 'annotate' | 'escalate' | 'draft_report' | 'freeze'
  tier: number
  target_id: string
  status: ActionStatus
  rationale?: string
  blast_radius?: BlastRadius | null
  outcome?: string | null
  approved_by?: string | null
  rejected_by?: string | null
  rejection_reason?: string | null
  refusal_reason?: string | null
}

export interface CaseRecord {
  id: string
  alert_id: string
  seed_account_id: string
  alert_reason?: string
  mode: 'single' | 'orchestrated'
  status: CaseStatus
  status_reason?: string | null
  created_at?: string
  updated_at?: string
  verdict?: Verdict | null
  circuit?: CircuitReport | null
  narrative?: Narrative | null
  findings?: Finding[] | null
}

export interface EvidenceNode {
  id: string
  kind: 'account' | 'device'
  account_kind?: string
  customer_id?: string | null
}

export interface EvidenceEdge extends EdgeDetail {
  channel?: string
  sources: string[]
}

export interface LedgerEntry {
  result_id: string
  tool: string
  params: Record<string, unknown>
  ts: string
}

export interface Evidence {
  nodes: EvidenceNode[]
  edges: EvidenceEdge[]
  ledger: Record<string, LedgerEntry>
  truncated: boolean
}

export interface CaseEvent {
  id: string
  case_id: string
  type: string
  data: Record<string, unknown>
  ts: string
}

export interface Recording {
  case_id: string
  events: CaseEvent[]
  snapshot: { case: CaseRecord; actions: Action[]; evidence: Evidence } | null
}
