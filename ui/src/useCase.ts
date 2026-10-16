// Live and replayed cases behind one interface: a CaseView, its evidence and the case record.
// Callers key these hooks' components by case ID, so a new case always starts from fresh state.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api, followEvents, type Connection } from './api'
import { evidenceSoFar, fold, overlay, type CaseView } from './caseState'
import type { Action, CaseEvent, CaseRecord, Evidence, Recording } from './types'

const REFRESH_ON = new Set([
  'hypotheses_chosen', 'investigation_started', 'finding', 'verification_started', 'verdict',
  'action_proposed', 'action_approved', 'action_executed', 'action_rejected', 'action_refused',
  'review_decision',
])
const MAX_REPLAY_GAP_MS = 1200

export interface CaseSession {
  view: CaseView
  record: CaseRecord | null
  evidence: Evidence | null
  connection: Connection
  error: string | null
  refresh: () => void
}

export function useLiveCase(caseId: string): CaseSession {
  const [events, setEvents] = useState<CaseEvent[]>([])
  const [record, setRecord] = useState<CaseRecord | null>(null)
  const [actions, setActions] = useState<Action[]>([])
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [error, setError] = useState<string | null>(null)
  const timers = useRef<{ record?: number; evidence?: number }>({})

  const loadRecord = useCallback(() => {
    api.getCase(caseId)
      .then((r) => { setRecord(r.case); setActions(r.actions); setError(null) })
      .catch((e: Error) => setError(e.message))
  }, [caseId])
  const loadEvidence = useCallback(() => {
    api.evidence(caseId).then(setEvidence).catch((e: Error) => setError(e.message))
  }, [caseId])

  useEffect(() => {
    loadRecord(); loadEvidence()
    const schedule = (key: 'record' | 'evidence', load: () => void) => {
      window.clearTimeout(timers.current[key])
      timers.current[key] = window.setTimeout(load, 250)
    }
    const stop = followEvents(caseId, (event) => {
      setEvents((seen) => (seen.some((e) => e.id === event.id) ? seen : [...seen, event]))
      if (event.type === 'tool_result' || event.type === 'verdict') {
        schedule('evidence', loadEvidence)
      }
      if (REFRESH_ON.has(event.type)) schedule('record', loadRecord)
    }, setConnection)
    const pending = timers.current
    return () => {
      stop()
      window.clearTimeout(pending.record)
      window.clearTimeout(pending.evidence)
    }
  }, [caseId, loadRecord, loadEvidence])

  const view = useMemo(() => overlay(fold(events), record, actions), [events, record, actions])
  const refresh = useCallback(() => { loadRecord(); loadEvidence() }, [loadRecord, loadEvidence])
  return { view, record, evidence, connection, error, refresh }
}

export interface ReplaySession extends CaseSession {
  playing: boolean
  position: number
  total: number
  play: () => void
  pause: () => void
  restart: () => void
  recordedAt: string | null
}

export function useReplay(caseId: string): ReplaySession {
  const [recording, setRecording] = useState<Recording | null>(null)
  const [position, setPosition] = useState(0)
  const [wantPlay, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.recording(caseId)
      .then((r) => { setRecording(r); setPlaying(true) })
      .catch((e: Error) => setError(e.message))
  }, [caseId])

  const events = useMemo(() => recording?.events ?? [], [recording])
  const playing = wantPlay && position < events.length
  useEffect(() => {
    if (!playing) return
    const previous = events[position - 1]
    const gap = previous
      ? Date.parse(events[position].ts) - Date.parse(previous.ts) : 0
    const timer = window.setTimeout(() => setPosition((p) => p + 1),
      Math.max(120, Math.min(gap, MAX_REPLAY_GAP_MS)))
    return () => window.clearTimeout(timer)
  }, [playing, position, events])

  const view = useMemo(() => fold(events.slice(0, position)), [events, position])
  const snapshot = recording?.snapshot ?? null
  const evidence = useMemo(
    () => (snapshot ? evidenceSoFar(snapshot.evidence, view.results,
      snapshot.case.seed_account_id) : null),
    [snapshot, view.results],
  )
  // Static facts (seed, reason) come from the snapshot; everything that changes, from events.
  const record = snapshot
    ? { ...snapshot.case, status: view.status ?? 'received', verdict: null, circuit: null,
        narrative: null, findings: null }
    : null
  const withRationale: CaseView = {
    ...view,
    actions: view.actions.map((a) => ({
      ...snapshot?.actions.find((s) => s.id === a.id), ...a,
    })),
  }
  return {
    view: withRationale, record, evidence, connection: 'live', error,
    refresh: () => undefined,
    playing, position, total: events.length,
    play: () => { if (position >= events.length) setPosition(0); setPlaying(true) },
    pause: () => setPlaying(false),
    restart: () => { setPosition(0); setPlaying(true) },
    recordedAt: events.at(-1)?.ts ?? null,
  }
}
