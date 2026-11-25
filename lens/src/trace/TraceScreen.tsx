// Device 2: the trace console. The decision the network on device 1 is making, traced live:
// its inputs, the attribution graph of its circuit and backup route, any neuron's card, the
// decision over time and a log of how it changed. Click a moment in the plot or the log to
// replay it; switch a neuron off and device 1 runs without it.
import { useCallback, useEffect, useMemo, useState } from 'react'

import { useLink, type LinkStatus, type Message, type Scenario, type SceneMessage } from '../link'
import type { Net } from '../model/net'
import { trace as traceDecision, type Trace } from '../model/trace'
import { useModels } from '../model/useModels'
import { sentence } from './Analytics'
import { Network3D } from './Network3D'
import {
  CircuitGraph, DecisionLog, InputsPanel, NeuronCard, OUTPUT_COLOURS, Panel, Telemetry, type Moment,
} from './panels'

const HISTORY = 240 // about a minute of decisions at four a second
const AGAINST: Record<Scenario, string> = {
  driving: 'the same moment on an empty road',
  aml: 'an average clear account',
}
const NAMES: Record<Scenario, string> = { driving: 'driving policy', aml: 'aml account check' }
const LINK_WORDS: Record<LinkStatus, string> = {
  connecting: 'connecting', alone: 'waiting for simulation', paired: 'paired', offline: 'relay offline',
}

export function TraceScreen({ room }: { room: string }) {
  const { models, error } = useModels()
  const [scenario, setScenario] = useState<Scenario>('driving')
  const [scenes, setScenes] = useState<Partial<Record<Scenario, SceneMessage>>>({})
  const [held, setHeld] = useState<Moment | null>(null)
  const [off, setOff] = useState<Record<Scenario, string[]>>({ driving: [], aml: [] })
  const [history, setHistory] = useState<Record<Scenario, Moment[]>>({ driving: [], aml: [] })
  const [log, setLog] = useState<Record<Scenario, Moment[]>>({ driving: [], aml: [] })
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<'graph' | '3d'>('graph')

  const onMessage = useCallback((m: Message) => {
    if (m.type === 'scenario') setScenario(m.scenario)
    if (m.type === 'scene') setScenes((s) => ({ ...s, [m.scenario]: m }))
    if (m.type === 'ablate') setOff((o) => ({ ...o, [m.scenario]: m.nodes }))
  }, [])
  const link = useLink(room, 'trace', onMessage)

  const net: Net | null = models ? models[scenario] : null
  const live = scenes[scenario]
  const scene = held ?? live
  const offSet = useMemo(() => new Set(off[scenario]), [off, scenario])
  const t: Trace | null = useMemo(() => (net && scene
    ? traceDecision(net, scene.x, scene.reference, { nodes: offSet }) : null), [net, scene, offSet])

  // Record each live decision; log it when the decision or its reason changes.
  useEffect(() => {
    if (!net || !live || held) return
    const lt = traceDecision(net, live.x, live.reference, { nodes: offSet })
    const m: Moment = { at: live.at, x: live.x, reference: live.reference, title: live.title,
      context: live.context, probs: lt.run.probs, choice: lt.choice, margin: lt.margin,
      cause: lt.circuit ? lt.circuit.evidence.join(' + ') : 'nothing unusual',
      backup: lt.backup ? lt.backup.evidence.join(' + ') : '' }
    setHistory((h) => ({ ...h, [scenario]: [...h[scenario], m].slice(-HISTORY) }))
    setLog((l) => {
      const prev = l[scenario][l[scenario].length - 1]
      if (prev && prev.choice === m.choice && prev.cause === m.cause && prev.backup === m.backup) return l
      return { ...l, [scenario]: [...l[scenario], m].slice(-60) }
    })
  }, [net, live, held, offSet, scenario])

  // A new scenario is a different network: its neurons share ids, not meaning.
  useEffect(() => { setSelected(null); setHeld(null) }, [scenario])

  // Open the strongest neuron of the circuit unless one is already chosen.
  useEffect(() => {
    if (!t?.circuit) return
    if (selected && net?.neurons.some((n) => n.id === selected)) return
    const top = [...t.circuit.hidden].sort((a, b) =>
      Math.abs(t.nodeAttr[b] ?? 0) - Math.abs(t.nodeAttr[a] ?? 0))[0]
    if (top) setSelected(top)
  }, [t, selected, net])

  const setNodes = (nodes: string[]) => {
    setOff((o) => ({ ...o, [scenario]: nodes }))
    link.send({ type: 'ablate', scenario, nodes })
  }
  const toggle = (id: string) =>
    setNodes(offSet.has(id) ? [...offSet].filter((n) => n !== id) : [...offSet, id])
  const pick = (m: Moment) => setHeld(m)

  const decision = net && t ? net.outputs[t.choice] : null

  return (
    <div className="console">
      <header className="strip">
        <a href="#/" className="brand">LATTICE LENS</a>
        <span className="seg">{NAMES[scenario]}</span>
        <span className={`seg state ${held ? 'held' : 'live'}`}>{held ? 'REPLAY' : 'LIVE'}</span>
        {scene && <span className="seg mono">
          {new Date(scene.at).toLocaleTimeString('en-GB', { hour12: false })}</span>}
        {decision && t && (
          <span className="seg decision" style={{ color: OUTPUT_COLOURS[decision.id] }}>
            {decision.label.toUpperCase()} <span className="mono">{t.run.probs[t.choice].toFixed(2)}</span>
          </span>
        )}
        {net && t && <span className="seg said">{sentence(net, t, AGAINST[scenario])}</span>}
        <span className="grow" />
        {held && <button type="button" className="btn" onClick={() => setHeld(null)}>Back to live</button>}
        <span className={`seg link ${link.status}`}><i />{LINK_WORDS[link.status]} · {room}</span>
      </header>

      {error && <p className="console-msg">{error}</p>}
      {(!net || !scene || !t) ? (
        <p className="console-msg">Waiting for the simulation. Open it on the other device with room
          code <span className="mono">{room}</span>.</p>
      ) : (
        <div className="grid">
          <Panel title="inputs" area="inputs"
            aside={<span className="dim">vs {scenario === 'driving' ? 'empty road' : 'avg clear account'}</span>}>
            <p className="scene-title">{scene.title}</p>
            <InputsPanel net={net} t={t} x={scene.x} reference={scene.reference} />
            <ul className="context">{scene.context.map((c) => <li key={c}>{c}</li>)}</ul>
          </Panel>

          <Panel area="graph" title={view === 'graph' ? 'attribution graph' : 'network, 3d'}
            aside={
              <span className="tabs" role="group" aria-label="Graph view">
                <button type="button" aria-pressed={view === 'graph'} onClick={() => setView('graph')}>
                  circuit</button>
                <button type="button" aria-pressed={view === '3d'} onClick={() => setView('3d')}>3d</button>
              </span>
            }>
            {view === 'graph'
              ? <CircuitGraph net={net} t={t} selected={selected} off={offSet} onSelect={setSelected} />
              : <Network3D net={net} trace={t} off={offSet} onToggle={toggle} />}
            <div className="graph-legend">
              <span className="k circuit">circuit: {t.circuit?.evidence.join(' + ') ?? 'none'}</span>
              <span className="k backup">backup: {t.backup?.evidence.join(' + ') ?? 'none'}</span>
              {t.circuit && t.circuit.fired.length > 0 && (
                <button type="button" className="btn danger"
                  onClick={() => setNodes([...new Set([...offSet, ...t.circuit!.fired])])}>
                  ablate circuit detectors</button>
              )}
              {offSet.size > 0 && <button type="button" className="btn" onClick={() => setNodes([])}>
                restore all ({offSet.size} off)</button>}
            </div>
          </Panel>

          <Panel area="neuron" title={selected ? `neuron ${selected}` : 'neuron'}>
            <NeuronCard net={net} t={t} id={selected} off={offSet} onToggle={toggle} />
          </Panel>

          <Panel area="plots" title="telemetry">
            <Telemetry net={net} moments={history[scenario]} held={held?.at ?? null} onPick={pick} />
          </Panel>

          <Panel area="log" title="decision log">
            <DecisionLog net={net} entries={log[scenario]} held={held?.at ?? null} onPick={pick} />
          </Panel>
        </div>
      )}
    </div>
  )
}
