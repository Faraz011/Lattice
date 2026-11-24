// Device 2: inside the network that makes the decision on device 1, traced live.
import { useCallback, useMemo, useState } from 'react'

import { TopBar } from '../TopBar'
import { useLink, type Message, type Scenario, type SceneMessage } from '../link'
import type { Net } from '../model/net'
import { trace as traceDecision, type Route, type Trace } from '../model/trace'
import { useModels } from '../model/useModels'
import { NetworkDiagram } from './NetworkDiagram'

const AGAINST: Record<Scenario, string> = {
  driving: 'the same moment on an empty road',
  aml: 'an average clear account',
}
const TITLES: Record<Scenario, string> = { driving: 'Self-driving car', aml: 'Money laundering check' }

export function TraceScreen({ room }: { room: string }) {
  const { models, error } = useModels()
  const [scenario, setScenario] = useState<Scenario>('driving')
  const [scenes, setScenes] = useState<Partial<Record<Scenario, SceneMessage>>>({})
  const [held, setHeld] = useState<SceneMessage | null>(null)
  const [off, setOff] = useState<Record<Scenario, string[]>>({ driving: [], aml: [] })

  const onMessage = useCallback((m: Message) => {
    if (m.type === 'scenario') setScenario(m.scenario)
    if (m.type === 'scene') setScenes((s) => ({ ...s, [m.scenario]: m }))
    if (m.type === 'ablate') setOff((o) => ({ ...o, [m.scenario]: m.nodes }))
  }, [])
  const link = useLink(room, 'trace', onMessage)

  const net: Net | null = models ? models[scenario] : null
  const live = scenes[scenario]
  const scene = held && held.scenario === scenario ? held : live
  const offSet = useMemo(() => new Set(off[scenario]), [off, scenario])
  const t: Trace | null = useMemo(() => (net && scene
    ? traceDecision(net, scene.x, scene.reference, { nodes: offSet }) : null), [net, scene, offSet])

  const setNodes = (nodes: string[]) => {
    setOff((o) => ({ ...o, [scenario]: nodes }))
    link.send({ type: 'ablate', scenario, nodes })
  }
  const toggle = (id: string) =>
    setNodes(offSet.has(id) ? [...offSet].filter((n) => n !== id) : [...offSet, id])

  return (
    <>
      <TopBar room={room} link={link} role="Inside the model">
        <strong>{TITLES[scenario]}</strong>
        {scene && (
          <button type="button" className={held ? 'primary' : undefined}
            onClick={() => setHeld(held ? null : scene)}>
            {held ? 'Back to live' : 'Hold this moment'}</button>
        )}
      </TopBar>
      {error && <p className="banner" role="alert">{error}</p>}
      {(!net || !scene || !t) ? (
        <div className="waiting">
          <h2>Waiting for the simulation</h2>
          <p className="muted">Open the simulation on the other device with room code{' '}
            <code>{room}</code>. Its decisions appear here as they happen.</p>
        </div>
      ) : (
        <div className="trace">
          <main className="trace-main">
            <div className="verdict-line">
              <span className="word">{scene.title}: {net.outputs[t.choice].label}</span>
              <span className="muted">{Math.round(t.run.probs[t.choice] * 100)}% over{' '}
                {net.outputs[t.runnerUp].label}</span>
              <span className="against">{held ? 'Held. ' : 'Live. '}Compared with {AGAINST[scenario]}.</span>
            </div>
            <ul className="facts muted">{scene.context.map((c) => <li key={c}>{c}</li>)}</ul>
            <NetworkDiagram net={net} trace={t} off={offSet} onToggle={toggle} />
            <p className="legend">
              <span>The circuit: the fewest neurons that make this decision</span>
              <span className="k-backup">The backup route, if the circuit is switched off</span>
              <span className="k-push">Pushes toward the decision</span>
              <span className="k-against">Pushes against it</span>
            </p>
          </main>
          <aside className="explain">
            <Explanation net={net} t={t} scenario={scenario} off={offSet} setNodes={setNodes} />
          </aside>
        </div>
      )}
    </>
  )
}

function Explanation({ net, t, scenario, off, setNodes }: {
  net: Net; t: Trace; scenario: Scenario; off: ReadonlySet<string>; setNodes: (n: string[]) => void
}) {
  const label = (id: string) => net.neurons.find((n) => n.id === id)?.label ?? id
  const decision = net.outputs[t.choice].label
  const evidence = (r: Route) => cap(r.evidence.join(' and '))
  const switchOff = (r: Route) => setNodes([...new Set([...off, ...r.fired])])
  const thing = scenario === 'driving' ? 'scene' : 'account'

  return (
    <>
      {t.reference.choice === t.choice ? (
        <section>
          <h3>Nothing out of the ordinary</h3>
          <p className="muted">The network decides <strong>{decision}</strong> here, the same as it
            does for {AGAINST[scenario]}. There is no circuit to show until something in the
            {' '}{thing} changes the decision.</p>
        </section>
      ) : !t.circuit ? (
        <section>
          <h3>No small circuit</h3>
          <p className="muted">The decision differs from {AGAINST[scenario]}, but no smaller part
            of the {thing} reproduces it on its own.</p>
        </section>
      ) : (
        <>
          <section className="route first">
            <h3>Why {decision}: the circuit</h3>
            <p className="muted">On this evidence alone, with everything else as on
              {' '}{AGAINST[scenario]}, the network still decides {decision}
              {' '}(margin {t.circuit.margin.toFixed(1)}):</p>
            <p><strong>{evidence(t.circuit)}</strong></p>
            <Neurons r={t.circuit} label={label} />
            {t.circuit.fired.length > 0 ? (
              <button type="button" className="seal" onClick={() => switchOff(t.circuit!)}>
                Switch off the {t.circuit.fired.length === 1 ? 'detector' : `${t.circuit.fired.length} detectors`}
                {' '}it fires</button>
            ) : (
              <p className="muted">This route works by silencing neurons, so there is no detector
                here to switch off.</p>
            )}
          </section>
          {t.backup ? (
            <section className="route second">
              <h3>The backup route</h3>
              <p className="muted">The rest of the {thing} is a second, separate reason for
                {' '}{decision} (margin {t.backup.margin.toFixed(1)}):</p>
              <p><strong>{evidence(t.backup)}</strong></p>
              <Neurons r={t.backup} label={label} />
              <p className="muted">Reading the circuit alone, you would not know it exists. Switch
                the circuit's detectors off and the {scenario === 'driving' ? 'car' : 'bank'} still
                {' '}decides {decision}, through this.</p>
            </section>
          ) : (
            <section className="route">
              <h3>No backup route</h3>
              <p className="muted">Nothing else in the {thing} gives {decision} on its own. Take
                away the circuit's evidence and the decision changes: it is essential here.</p>
            </section>
          )}
        </>
      )}
      <section>
        <h3>Switched off</h3>
        {off.size === 0 ? <p className="muted">Nothing. Click a neuron in the drawing to switch it
          off; the {scenario === 'driving' ? 'car' : 'bank'} on the other device runs without it.</p> : (
          <>
            <ul className="facts">{[...off].map((n) => <li key={n}>{label(n)}</li>)}</ul>
            <button type="button" onClick={() => setNodes([])}>Switch everything back on</button>
          </>
        )}
      </section>
      <section>
        <h3>About this network</h3>
        <p className="muted">{net.notes} {net.sizes.slice(1, -1).reduce((a, b) => a + b, 0)} hidden
          neurons. {metric(net)}</p>
      </section>
    </>
  )
}

// "quiet when pedestrian in the path (3 neurons)" rather than the same line three times.
// A route's neurons by what it does to them: the detectors it switches on, the ones it quiets,
// and how many later neurons combine them.
function Neurons({ r, label }: { r: Route; label: (id: string) => string }) {
  return (
    <ul>
      {r.fired.length > 0 && <li>switches on: {grouped(r.fired.map(label)).join('; ')}</li>}
      {r.silenced.length > 0 && <li>quiets: {grouped(r.silenced.map(label)).join('; ')}</li>}
      {r.combined.length > 0 && <li>combined in {r.combined.length} neuron
        {r.combined.length === 1 ? '' : 's'} of the next layer</li>}
    </ul>
  )
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

function grouped(labels: string[]): string[] {
  const counts = new Map<string, number>()
  for (const l of labels) counts.set(l, (counts.get(l) ?? 0) + 1)
  return [...counts].map(([l, n]) => (n > 1 ? `${l} (${n} neurons)` : l))
}

function metric(net: Net): string {
  const m = net.metrics as Record<string, number>
  if (m.agreement_with_expert) return `Agrees with the expert driver ${Math.round(m.agreement_with_expert * 1000) / 10}% of the time on situations it never saw.`
  if (m.accuracy) return `${Math.round(m.accuracy * 1000) / 10}% correct on accounts from worlds it never saw.`
  return ''
}
