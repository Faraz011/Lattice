// What a person wants to know about a decision, in plain words and small charts: a sentence, what
// drove it, how sure the network has been over time, and what would change its mind.
import { useMemo, useState } from 'react'

import { drivers, levers, whatIf, type Driver } from '../model/analytics'
import type { Ablation, Net } from '../model/net'
import type { Trace } from '../model/trace'

const COLOURS = ['#2f6b4f', '#4b5670', '#a3233a', '#85661c', '#6b4fa3']

export interface Moment { at: number; probs: number[]; choice: number }

const join = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)

// One sentence a panel can read aloud.
export function sentence(net: Net, t: Trace, against: string): string {
  const d = net.outputs[t.choice].label
  if (t.reference.choice === t.choice) {
    return `It decides ${d}, as it would for ${against}: nothing here changes its mind.`
  }
  const because = t.circuit ? join(t.circuit.evidence) : 'this situation'
  let out = `It decides ${d} because of ${because}.`
  if (t.backup) {
    out += ` Without that, ${join(t.backup.evidence)} alone would still make it ${d}.`
  } else if (t.circuit) {
    out += ` Without ${because}, it would ${net.outputs[t.reference.choice].label}.`
  }
  return out
}

export function Drivers({ net, list, choice }: { net: Net; list: Driver[]; choice: number }) {
  if (!list.length) return <p className="muted">Nothing here differs from the reference.</p>
  return (
    <ul className="drivers">
      {list.map((d) => (
        <li key={d.label}>
          <div className="driver-head">
            <span>{d.label}</span>
            <span className="muted">{Math.round(d.share * 100)}%</span>
          </div>
          <div className="meter"><span className={d.effect >= 0 ? 'for' : 'against'}
            style={{ width: `${Math.max(3, d.share * 100)}%` }} /></div>
          <p className="muted">Take it away and it would {d.without === choice
            ? `still ${net.outputs[d.without].label}` : net.outputs[d.without].label}.</p>
        </li>
      ))}
    </ul>
  )
}

// How sure it has been, decision by decision, over the last moments: one band per output.
export function Timeline({ net, moments }: { net: Net; moments: Moment[] }) {
  const W = 320
  const H = 90
  if (moments.length < 2) return <p className="muted">Builds up as decisions come in.</p>
  const n = moments.length
  const x = (i: number) => (i / (n - 1)) * W
  const bands = net.outputs.map((_, k) => {
    const lower = moments.map((m) => m.probs.slice(0, k).reduce((a, b) => a + b, 0))
    const upper = moments.map((m, i) => lower[i] + m.probs[k])
    const top = upper.map((v, i) => `${x(i)},${H - v * H}`).join(' ')
    const bottom = lower.map((v, i) => `${x(i)},${H - v * H}`).reverse().join(' ')
    return `${top} ${bottom}`
  })
  return (
    <figure className="timeline">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label="How sure the network has been of each decision, oldest on the left">
        {bands.map((pts, k) => <polygon key={k} points={pts} fill={COLOURS[k % COLOURS.length]}
          opacity={0.85} />)}
      </svg>
      <figcaption>
        {net.outputs.map((o, k) => (
          <span key={o.id}><i style={{ background: COLOURS[k % COLOURS.length] }} />{o.label}</span>
        ))}
      </figcaption>
    </figure>
  )
}

// Inputs the presenter can move to see what would change the decision. Runs here only: the
// simulation on the other device is not touched.
const UNITS: Record<string, { label: string; max: number; to: (v: number) => number;
  from: (u: number) => number; unit: string }> = {
  speed: { label: 'Speed', max: 72, unit: 'km/h', to: (v) => v * 72, from: (u) => u / 72 },
  light_near: { label: 'Distance to the light', max: 120, unit: 'm',
    to: (v) => (1 - v) * 120, from: (u) => 1 - u / 120 },
  crosswalk_near: { label: 'Distance to the crossing', max: 120, unit: 'm',
    to: (v) => (1 - v) * 120, from: (u) => 1 - u / 120 },
  lead_near: { label: 'Gap to the car ahead', max: 120, unit: 'm',
    to: (v) => (1 - v) * 120, from: (u) => 1 - u / 120 },
}
const SWITCHES = new Set(['light_red', 'light_yellow', 'light_green', 'ped_crossing', 'ped_waiting',
  'lead_car', 'rain', 'night', 'cycle', 'to_exit'])

export function WhatIf({ net, x, t, base }: { net: Net; x: number[]; t: Trace; base: Ablation }) {
  const picks = useMemo(() => levers(net, t.nodeAttr, 4), [net, t])
  const [changes, setChanges] = useState<Record<number, number>>({})
  const live = Object.fromEntries(Object.entries(changes).filter(([i]) => picks.includes(Number(i))))
  const run = whatIf(net, x, base, live)
  const changed = run.choice !== t.choice
  return (
    <div className="whatif">
      {picks.map((i) => {
        const f = net.inputs[i]
        const v = i in live ? live[i] : x[i]
        const set = (nv: number) => setChanges((c) => ({ ...c, [i]: nv }))
        if (SWITCHES.has(f.id)) {
          return (
            <label key={f.id} className="lever switch-lever">
              <input type="checkbox" checked={v > 0.5} onChange={(e) => set(e.target.checked ? 1 : 0)} />
              {f.label}
            </label>
          )
        }
        const u = UNITS[f.id]
        return (
          <label key={f.id} className="lever">
            <span>{u?.label ?? f.label}<b>{u ? `${Math.round(u.to(v))} ${u.unit}` : v.toFixed(2)}</b></span>
            <input type="range" min={0} max={u ? u.max : 1} step={u ? 1 : 0.01}
              value={u ? u.to(v) : v}
              onChange={(e) => set(u ? u.from(Number(e.target.value)) : Number(e.target.value))} />
          </label>
        )
      })}
      <p className={changed ? 'whatif-out changed' : 'whatif-out'} role="status">
        {changed ? 'It would change its mind: ' : 'It would still decide: '}
        <strong>{net.outputs[run.choice].label}</strong> ({Math.round(run.probs[run.choice] * 100)}%)
      </p>
      {Object.keys(live).length > 0 && (
        <button type="button" className="quiet" onClick={() => setChanges({})}>Back to the real values</button>
      )}
    </div>
  )
}

export { drivers }
