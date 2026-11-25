// The trace console's panels: the network's inputs, the attribution graph of the decision's
// circuit, the selected neuron's card, telemetry over time and the decision log.
import type { ReactNode } from 'react'

import type { Net } from '../model/net'
import type { Trace } from '../model/trace'

export interface Moment {
  at: number
  x: number[]
  reference: number[]
  title: string
  context: string[]
  probs: number[]
  choice: number
  margin: number
  cause: string
  backup: string
}

export interface NeuronProfile {
  id: string
  label: string
  layer: number
  pushes: string | null
  dead: boolean
  active?: number
  examples?: { text: string; act: number }[]
  hist?: { max: number; counts: number[] }
  concepts?: { concept: string; corr: number }[]
}

export const OUTPUT_COLOURS: Record<string, string> = {
  brake: 'var(--c-brake)', accelerate: 'var(--c-go)', cruise: 'var(--c-info)',
  clear: 'var(--c-go)', layering: 'var(--c-brake)', structuring: 'var(--c-warn)',
  round_trip: '#c77dff', device_ring: '#ff8f6b',
}

export function Panel({ title, area, aside, children }: {
  title: ReactNode; area: string; aside?: ReactNode; children: ReactNode
}) {
  return (
    <section className={`panel panel-${area}`} style={{ gridArea: area }}>
      <header><h2>{title}</h2>{aside}</header>
      <div className="panel-body">{children}</div>
    </section>
  )
}

// An input's value in the units a person reads it in.
export function reading(net: Net, i: number, v: number): string {
  const id = net.inputs[i].id
  const flag = (on: boolean) => (on ? 'yes' : 'no')
  if (net.name === 'driving') {
    const metres = (near: number) => (near > 0 ? `${Math.round((1 - near) * 120)} m` : 'none')
    switch (id) {
      case 'speed': return `${Math.round(v * 72)} km/h`
      case 'light_near': case 'crosswalk_near': case 'lead_near': return metres(v)
      case 'closing': return `${Math.round(v * 72)} km/h`
      default: return flag(v > 0.5)
    }
  }
  const count = (scale: number) => `${Math.round(Math.expm1(v * Math.log1p(scale)))}`
  switch (id) {
    case 'in_count': case 'out_count': return count(30)
    case 'senders': case 'receivers': return count(20)
    case 'in_amount': return `€${Number(count(1_000_000)).toLocaleString('en-GB')}`
    case 'forward_ratio': case 'fast_forward': case 'new_counterparties': return `${Math.round(v * 100)}%`
    case 'near_threshold': return `${Math.round(v * 8)}`
    case 'new_account': return `${Math.round((1 - v) * 365)} d old`
    case 'chain_depth': return `${Math.round(v * 6)} hops`
    case 'shared_device': return `${Math.round(v * 5)} accts`
    default: return flag(v > 0.5)
  }
}

export function InputsPanel({ net, t, x, reference }: {
  net: Net; t: Trace; x: number[]; reference: number[]
}) {
  const used = new Set([...(t.circuit?.inputs ?? [])])
  const backup = new Set([...(t.backup?.inputs ?? [])])
  return (
    <table className="inputs">
      <thead><tr><th>input</th><th className="num">value</th><th className="num">attr</th></tr></thead>
      <tbody>
        {net.inputs.map((f, i) => {
          const a = t.nodeAttr[`x${i}`] ?? 0
          const moved = Math.abs(x[i] - reference[i]) > 1e-9
          const role = used.has(i) ? 'circuit' : backup.has(i) ? 'backup' : moved ? 'moved' : ''
          return (
            <tr key={f.id} className={role} title={f.description}>
              <td><i className="dot" />{f.id}</td>
              <td className="num">
                <span className="meter"><span style={{ width: `${Math.min(1, Math.abs(x[i])) * 100}%` }} /></span>
                {reading(net, i, x[i])}
              </td>
              <td className={`num ${a > 0.005 ? 'pos' : a < -0.005 ? 'neg' : 'zero'}`}>
                {Math.abs(a) < 0.005 ? '·' : `${a > 0 ? '+' : ''}${a.toFixed(2)}`}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// The circuit as an attribution graph: only the inputs and neurons the routes use, in layers,
// edge width by attribution. Click a neuron to open its card.
export function CircuitGraph({ net, t, selected, off, onSelect }: {
  net: Net; t: Trace; selected: string | null; off: ReadonlySet<string>; onSelect: (id: string) => void
}) {
  const depth = net.layers.length
  if (!t.circuit) {
    return <p className="empty">No circuit: the network makes the same choice as for the reference input.
      Nothing in this {net.name === 'driving' ? 'scene' : 'account'} changes its mind.</p>
  }
  const W = 900
  const nodes = new Set([...t.circuit.nodes, ...(t.backup?.nodes ?? [])])
  nodes.add(`y${t.choice}`)
  const layers: string[][] = Array.from({ length: depth + 1 }, () => [])
  for (const id of nodes) {
    const layer = id.startsWith('x') ? 0 : id.startsWith('y') ? depth : Number(id.slice(1).split('_')[0])
    layers[layer].push(id)
  }
  layers.forEach((l) => l.sort())
  const rows = Math.max(...layers.map((l) => l.length), 2)
  const H = Math.max(260, rows * 46 + 40)
  const NW = 156 // node width
  const colX = (layer: number) => NW / 2 + 12 + (layer / depth) * (W - NW - 24)
  const pos = new Map<string, { x: number; y: number }>()
  layers.forEach((l, layer) => l.forEach((id, k) => {
    pos.set(id, { x: colX(layer), y: 30 + ((k + 0.5) * (H - 60)) / l.length })
  }))
  const circuit = new Set(t.circuit.edges)
  const backup = new Set(t.backup?.edges ?? [])
  const edges = [...new Set([...circuit, ...backup])]
  const max = Math.max(1e-9, ...edges.map((e) => Math.abs(t.edgeAttr[e] ?? 0)))
  const ends = (e: string) => {
    const [l, i, j] = e.split(':').map(Number)
    const a = l === 0 ? `x${i}` : `h${l}_${i}`
    const b = l + 1 === depth ? `y${j}` : `h${l + 1}_${j}`
    return [pos.get(a), pos.get(b)]
  }
  const name = (id: string) => {
    if (id.startsWith('x')) return net.inputs[Number(id.slice(1))].id
    if (id.startsWith('y')) return net.outputs[Number(id.slice(1))].label.toUpperCase()
    return id
  }
  const act = (id: string) => {
    if (id.startsWith('x')) return t.run.acts[0][Number(id.slice(1))]
    if (id.startsWith('y')) return t.run.probs[Number(id.slice(1))]
    const [l, j] = id.slice(1).split('_').map(Number)
    return t.run.acts[l][j]
  }
  const sub = (id: string) => (id.startsWith('h')
    ? (net.neurons.find((n) => n.id === id)?.label ?? '') : '')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="graph" role="img"
      aria-label={`Attribution graph: ${t.circuit.hidden.length} neurons carry the decision`}>
      {['input', 'layer 1', 'layer 2', 'output'].slice(0, depth + 1).map((h, k) => (
        <text key={h} x={colX(k)} y={14} className="col-head" textAnchor="middle">{h}</text>
      ))}
      {edges.map((e) => {
        const [p, q] = ends(e)
        if (!p || !q) return null
        const inCircuit = circuit.has(e)
        const wv = 1 + 5 * Math.abs(t.edgeAttr[e] ?? 0) / max
        const mx = (p.x + q.x) / 2
        return <path key={e} d={`M${p.x + NW / 2},${p.y} C${mx},${p.y} ${mx},${q.y} ${q.x - NW / 2},${q.y}`}
          className={inCircuit ? 'edge circuit' : 'edge backup'} strokeWidth={wv} />
      })}
      {[...pos].map(([id, p]) => {
        const isHidden = id.startsWith('h')
        const role = t.circuit!.nodes.includes(id) ? 'circuit' : 'backup'
        const v = act(id)
        return (
          <g key={id} transform={`translate(${p.x - NW / 2},${p.y - 17})`}
            className={`node ${role}${selected === id ? ' selected' : ''}${off.has(id) ? ' off' : ''}${isHidden ? ' pick' : ''}`}
            onClick={isHidden ? () => onSelect(id) : undefined} role={isHidden ? 'button' : undefined}
            tabIndex={isHidden ? 0 : undefined}
            onKeyDown={isHidden ? (ev) => { if (ev.key === 'Enter') onSelect(id) } : undefined}>
            <rect width={NW} height={34} rx={3} />
            <text x={6} y={14} className="n-id">{name(id).slice(0, 15)}</text>
            <text x={NW - 6} y={14} className="n-val" textAnchor="end">{v.toFixed(2)}</text>
            <text x={6} y={28} className="n-sub">{sub(id).slice(0, 28)}</text>
          </g>
        )
      })}
    </svg>
  )
}

export function NeuronCard({ net, t, id, off, onToggle }: {
  net: Net; t: Trace; id: string | null; off: ReadonlySet<string>; onToggle: (id: string) => void
}) {
  const n = net.neurons.find((x) => x.id === id) as NeuronProfile | undefined
  if (!id || !n) return <p className="empty">Select a neuron in the graph.</p>
  const [l, j] = id.slice(1).split('_').map(Number)
  const now = t.run.acts[l][j]
  const ref = t.reference.acts[l][j]
  const hist = n.hist
  const peak = hist ? Math.max(1, ...hist.counts) : 1
  const isOff = off.has(id)
  const inRoute = t.circuit?.hidden.includes(id) ? 'circuit' : t.backup?.hidden.includes(id) ? 'backup' : null
  return (
    <div className="neuron">
      <p className="n-title"><span className="mono">{id}</span> {n.label}</p>
      <dl className="kv">
        <dt>layer</dt><dd>{l}</dd>
        <dt>now</dt><dd className="mono">{now.toFixed(3)}</dd>
        <dt>reference</dt><dd className="mono">{ref.toFixed(3)}</dd>
        <dt>pushes</dt><dd>{n.pushes ?? '–'}</dd>
        <dt>fires in</dt><dd className="mono">{n.active != null ? `${(n.active * 100).toFixed(1)}% of training` : '–'}</dd>
        <dt>route</dt><dd className={inRoute ?? ''}>{inRoute ?? 'not used'}</dd>
      </dl>
      {hist && (
        <figure className="hist">
          <figcaption>activation over training data</figcaption>
          <svg viewBox="0 0 160 40" preserveAspectRatio="none" role="img"
            aria-label={`Activation histogram; now ${now.toFixed(2)}`}>
            {hist.counts.map((c, k) => (
              <rect key={k} x={k * (160 / hist.counts.length) + 0.5} width={160 / hist.counts.length - 1}
                y={40 - (c / peak) * 38} height={(c / peak) * 38} className="bin" />
            ))}
            {now > 0 && <line x1={Math.min(159, (now / hist.max) * 160)} x2={Math.min(159, (now / hist.max) * 160)}
              y1={0} y2={40} className="now" />}
          </svg>
        </figure>
      )}
      {n.examples && n.examples.length > 0 && (
        <div className="examples">
          <p className="sub-head">top activations in training</p>
          <ol>
            {n.examples.map((e) => (
              <li key={e.text}><span className="mono">{e.act.toFixed(2)}</span>{e.text}</li>
            ))}
          </ol>
        </div>
      )}
      <button type="button" className={isOff ? 'btn on' : 'btn'} onClick={() => onToggle(id)}>
        {isOff ? 'Switch back on' : 'Switch off (ablate)'}</button>
    </div>
  )
}

// Time series: the probability of each output, and the decision's margin, over the history.
export function Telemetry({ net, moments, held, onPick }: {
  net: Net; moments: Moment[]; held: number | null; onPick: (m: Moment) => void
}) {
  const W = 600
  const H = 120
  if (moments.length < 2) return <p className="empty">Recording. Plots appear as decisions arrive.</p>
  const t0 = moments[0].at
  const t1 = moments[moments.length - 1].at
  const x = (at: number) => ((at - t0) / Math.max(1, t1 - t0)) * W
  const line = (vals: number[], lo: number, hi: number) => moments.map((m, i) =>
    `${i ? 'L' : 'M'}${x(m.at).toFixed(1)},${(H - ((vals[i] - lo) / (hi - lo)) * H).toFixed(1)}`).join(' ')
  const margins = moments.map((m) => Math.max(-10, Math.min(10, m.margin)))
  const pick = (ev: React.MouseEvent<SVGSVGElement>) => {
    const r = ev.currentTarget.getBoundingClientRect()
    const at = t0 + ((ev.clientX - r.left) / r.width) * (t1 - t0)
    const best = moments.reduce((a, b) => (Math.abs(b.at - at) < Math.abs(a.at - at) ? b : a))
    onPick(best)
  }
  return (
    <div className="telemetry">
      <div className="legend-row">
        {net.outputs.map((o) => <span key={o.id}><i style={{ background: OUTPUT_COLOURS[o.id] }} />p({o.label})</span>)}
        <span><i className="margin-key" />margin</span>
        <span className="muted-mono">{((t1 - t0) / 1000).toFixed(0)} s · click to replay a moment</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="plot" onClick={pick}
        role="img" aria-label="Probabilities and margin over time">
        {[0.25, 0.5, 0.75].map((g) => <line key={g} x1={0} x2={W} y1={H * g} y2={H * g} className="grid" />)}
        {net.outputs.map((o, k) => (
          <path key={o.id} d={line(moments.map((m) => m.probs[k]), 0, 1)} className="series"
            style={{ stroke: OUTPUT_COLOURS[o.id] }} />
        ))}
        <path d={line(margins, -10, 10)} className="series margin" />
        {held != null && <line x1={x(held)} x2={x(held)} y1={0} y2={H} className="cursor" />}
      </svg>
    </div>
  )
}

export function DecisionLog({ net, entries, held, onPick }: {
  net: Net; entries: Moment[]; held: number | null; onPick: (m: Moment) => void
}) {
  if (!entries.length) return <p className="empty">Decisions are logged as they change.</p>
  return (
    <table className="log">
      <colgroup><col style={{ width: 78 }} /><col style={{ width: 96 }} /><col style={{ width: 40 }} />
        <col /></colgroup>
      <thead><tr><th>time</th><th>decision</th><th className="num">p</th><th>because / backup</th></tr></thead>
      <tbody>
        {[...entries].reverse().map((m) => (
          <tr key={m.at} className={held === m.at ? 'held' : undefined} onClick={() => onPick(m)}
            title="Replay this moment">
            <td className="mono">{new Date(m.at).toLocaleTimeString('en-GB', { hour12: false })}
              .{String(m.at % 1000).padStart(3, '0').slice(0, 1)}</td>
            <td><b style={{ color: OUTPUT_COLOURS[net.outputs[m.choice].id] }}>
              {net.outputs[m.choice].label.toUpperCase()}</b></td>
            <td className="num mono">{m.probs[m.choice].toFixed(2)}</td>
            <td>{m.cause}{m.backup && <span className="dim backup-line">backup: {m.backup}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
