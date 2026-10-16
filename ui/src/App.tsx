import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { AlertList } from './components/AlertList'
import { CaseScreen } from './components/CaseScreen'
import type { Alert } from './types'
import { useLiveCase, useReplay } from './useCase'

type Route = { kind: 'none' } | { kind: 'case' | 'replay'; caseId: string }

function readRoute(): Route {
  const [kind, caseId] = window.location.hash.replace(/^#\/?/, '').split('/')
  if ((kind === 'case' || kind === 'replay') && caseId) return { kind, caseId }
  return { kind: 'none' }
}

function LiveCase({ caseId, onChanged }: { caseId: string; onChanged: () => void }) {
  return <CaseScreen session={useLiveCase(caseId)} onChanged={onChanged} />
}

function ReplayCase({ caseId }: { caseId: string }) {
  const replay = useReplay(caseId)
  return <CaseScreen session={replay} replay={replay} />
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute)
  const [alerts, setAlerts] = useState<Alert[] | null>(null)
  const [alertsError, setAlertsError] = useState<string | null>(null)
  const [mode, setMode] = useState<'single' | 'orchestrated'>('orchestrated')
  const [starting, setStarting] = useState<string | null>(null)

  const loadAlerts = useCallback(() => {
    api.alerts().then((a) => { setAlerts(a); setAlertsError(null) })
      .catch((e: Error) => setAlertsError(e.message))
  }, [])

  useEffect(() => {
    loadAlerts()
    const timer = window.setInterval(loadAlerts, 5000)
    const onHash = () => setRoute(readRoute())
    window.addEventListener('hashchange', onHash)
    return () => { window.clearInterval(timer); window.removeEventListener('hashchange', onHash) }
  }, [loadAlerts])

  const go = (kind: 'case' | 'replay', caseId: string) => {
    window.location.hash = `#/${kind}/${caseId}`
  }

  const investigate = async (alert: Alert) => {
    setStarting(alert.id)
    try {
      const { case: started } = await api.investigate(alert.id, mode)
      go('case', started.id)
      loadAlerts()
    } catch (e) {
      setAlertsError((e as Error).message)
    } finally {
      setStarting(null)
    }
  }

  return (
    <div className="app">
      <aside className="rail">
        <header className="brand">
          <p className="wordmark">Lattice</p>
          <p className="muted">Money-laundering alerts, investigated by agents and decided by
            you.</p>
        </header>
        <fieldset className="mode">
          <legend>New investigations use</legend>
          <label>
            <input type="radio" name="mode" checked={mode === 'orchestrated'}
              onChange={() => setMode('orchestrated')} />
            One investigator per pattern
          </label>
          <label>
            <input type="radio" name="mode" checked={mode === 'single'}
              onChange={() => setMode('single')} />
            One investigator for everything
          </label>
        </fieldset>
        <h2 className="rail-title">Alerts</h2>
        <AlertList alerts={alerts} error={alertsError}
          selectedCase={route.kind === 'none' ? null : route.caseId} starting={starting}
          onInvestigate={investigate} onOpen={(id) => go('case', id)}
          onReplay={(id) => go('replay', id)} />
      </aside>
      <main className="main">
        {route.kind === 'case' && <LiveCase key={route.caseId} caseId={route.caseId}
          onChanged={loadAlerts} />}
        {route.kind === 'replay' && <ReplayCase key={route.caseId} caseId={route.caseId} />}
        {route.kind === 'none' && (
          <div className="welcome">
            <h1>Pick an alert to investigate</h1>
            <p>Agents walk the transaction graph from the flagged account, each testing one
              laundering pattern. Every edge they cite is checked against the record of what
              their tools actually returned. You see the smallest set of transfers that proves
              the verdict, and nothing is frozen until you approve it.</p>
          </div>
        )}
      </main>
    </div>
  )
}
