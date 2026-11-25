// Panels for the studies of a decision: the activity raster, the ablation table, the logit
// attribution and the input sensitivity curves.
import { useEffect, useRef } from 'react'

import type { Net } from '../model/net'
import type { AblationRow, Contribution, Sweep } from '../model/studies'
import type { Trace } from '../model/trace'
import { OUTPUT_COLOURS, reading, type Moment } from './panels'

// Every hidden neuron's activity over the recorded decisions: one row per neuron, one column
// per decision, brighter for stronger. The circuit's rows are marked.
export function Raster({ net, moments, t, held, onPick }: {
  net: Net; moments: Moment[]; t: Trace; held: number | null; onPick: (m: Moment) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const ids = net.neurons.map((n) => n.id)
  const circuit = new Set(t.circuit?.hidden ?? [])
  const backup = new Set(t.backup?.hidden ?? [])
  const peaks = net.neurons.map((n) => (n as { hist?: { max: number } }).hist?.max || 1)
  useEffect(() => {
    const c = canvas.current
    if (!c) return
    const cols = Math.max(1, moments.length)
    c.width = cols
    c.height = ids.length
    const g = c.getContext('2d')!
    const img = g.createImageData(cols, ids.length)
    moments.forEach((m, x) => {
      const acts = m.acts ?? []
      ids.forEach((_, y) => {
        const v = Math.max(0, Math.min(1, (acts[y] ?? 0) / peaks[y]))
        const [r, gg, b] = inferno(v)
        const k = (y * cols + x) * 4
        img.data[k] = r
        img.data[k + 1] = gg
        img.data[k + 2] = b
        img.data[k + 3] = 255
      })
    })
    g.putImageData(img, 0, 0)
  }, [moments, ids, peaks])
  if (moments.length < 2) return <p className="empty">Recording neuron activity.</p>
  const pick = (ev: React.MouseEvent<HTMLCanvasElement>) => {
    const r = ev.currentTarget.getBoundingClientRect()
    const k = Math.floor(((ev.clientX - r.left) / r.width) * moments.length)
    const m = moments[Math.max(0, Math.min(moments.length - 1, k))]
    if (m) onPick(m)
  }
  const heldX = held == null ? null : moments.findIndex((m) => m.at === held)
  return (
    <div className="raster">
      <ol className="raster-rows" aria-hidden="true">
        {ids.map((id) => (
          <li key={id} className={circuit.has(id) ? 'circuit' : backup.has(id) ? 'backup' : ''}>{id}</li>
        ))}
      </ol>
      <div className="raster-plot">
        <canvas ref={canvas} onClick={pick} role="img"
          aria-label={`Activity of ${ids.length} neurons over ${moments.length} decisions`} />
        {heldX != null && heldX >= 0 && (
          <span className="raster-cursor" style={{ left: `${(heldX / moments.length) * 100}%` }} />
        )}
      </div>
    </div>
  )
}

// A perceptual colour ramp (after matplotlib's inferno): dark for silent, through purple and
// orange, to pale yellow for a neuron at its strongest.
const STOPS: [number, number, number][] = [[18, 16, 30], [66, 10, 104], [147, 38, 103], [221, 81, 58],
  [252, 165, 10], [250, 240, 160]]
function inferno(v: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, v)) * (STOPS.length - 1)
  const i = Math.min(STOPS.length - 2, Math.floor(x))
  const f = x - i
  return STOPS[i].map((c, k) => Math.round(c + (STOPS[i + 1][k] - c) * f)) as [number, number, number]
}

export function AblationTable({ net, rows, onSelect, onToggle, off }: {
  net: Net; rows: AblationRow[]; onSelect: (id: string) => void; onToggle: (id: string) => void
  off: ReadonlySet<string>
}) {
  const max = Math.max(1e-6, ...rows.map((r) => Math.abs(r.delta)))
  return (
    <table className="ablate">
      <colgroup><col style={{ width: 54 }} /><col /><col style={{ width: 86 }} /><col style={{ width: 78 }} />
        <col style={{ width: 42 }} /></colgroup>
      <thead><tr><th>neuron</th><th>reads as</th><th>margin lost</th><th>decision</th><th /></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className={r.role}>
            <td className="mono"><button type="button" className="link" onClick={() => onSelect(r.id)}>{r.id}</button></td>
            <td className="trunc">{net.neurons.find((n) => n.id === r.id)?.label}</td>
            <td className="num">
              <span className="dbar"><span className={r.delta >= 0 ? 'loss' : 'gain'}
                style={{ width: `${(Math.abs(r.delta) / max) * 100}%` }} /></span>
              <span className="mono">{r.delta >= 0 ? '-' : '+'}{Math.abs(r.delta).toFixed(2)}</span>
            </td>
            <td>{r.flips == null ? <span className="dim">holds</span>
              : <b style={{ color: OUTPUT_COLOURS[net.outputs[r.flips].id] }}>→ {net.outputs[r.flips].label}</b>}</td>
            <td><button type="button" className={off.has(r.id) ? 'mini on' : 'mini'} onClick={() => onToggle(r.id)}
              title={off.has(r.id) ? 'Switch back on' : 'Switch off on both devices'}>{off.has(r.id) ? 'on' : 'off'}</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function LogitBars({ net, t, list, onSelect }: {
  net: Net; t: Trace; list: Contribution[]; onSelect: (id: string) => void
}) {
  const max = Math.max(1e-6, ...list.map((c) => Math.abs(c.value)))
  const total = list.reduce((s, c) => s + c.value, 0)
  return (
    <div className="logit">
      <p className="sub-head">{net.outputs[t.choice].label} over {net.outputs[t.runnerUp].label}:
        <span className="mono"> {total >= 0 ? '+' : ''}{total.toFixed(2)}</span></p>
      {list.map((c) => (
        <button key={c.id} type="button" className="logit-row" onClick={() => onSelect(c.id)}>
          <span className="mono">{c.id}</span>
          <span className="axis"><span className={c.value >= 0 ? 'for' : 'against'}
            style={{ width: `${(Math.abs(c.value) / max) * 50}%`,
              [c.value >= 0 ? 'left' : 'right']: '50%' }} /></span>
          <span className="mono">{c.value >= 0 ? '+' : ''}{c.value.toFixed(2)}</span>
        </button>
      ))}
    </div>
  )
}

// The chosen output's probability as each key input sweeps its range; the dot is now.
export function SensitivityCurves({ net, t, sweeps }: { net: Net; t: Trace; sweeps: Sweep[] }) {
  const W = 120
  const H = 46
  const colour = OUTPUT_COLOURS[net.outputs[t.choice].id]
  return (
    <div className="sens">
      {sweeps.map((s) => {
        const path = s.values.map((v, k) => `${k ? 'L' : 'M'}${(v * W).toFixed(1)},${(H - s.probs[k] * H).toFixed(1)}`).join(' ')
        const nowP = s.probs[Math.round(s.now * (s.values.length - 1))] ?? 0
        return (
          <figure key={s.input}>
            <figcaption><span className="mono">{net.inputs[s.input].id}</span>
              <span className="dim"> now {reading(net, s.input, s.now)}</span></figcaption>
            <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
              aria-label={`p(${net.outputs[t.choice].label}) as ${net.inputs[s.input].id} varies`}>
              <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="mid" />
              <path d={path} style={{ stroke: colour }} className="curve" />
              <circle cx={s.now * W} cy={H - nowP * H} r={3} style={{ fill: colour }} />
            </svg>
          </figure>
        )
      })}
    </div>
  )
}
