// The attribution graph of the whole network: every input, neuron and output in its column.
// The strongest connections are drawn faintly, red where they push toward the decision and
// blue where they push against it; the circuit is lit, with a signal running along it to the
// decision, and the backup route is dashed. Hover a neuron to isolate its connections; click a
// hidden one to open its card.
import { useState } from 'react'

import type { Net } from '../model/net'
import type { Trace } from '../model/trace'

const W = 1100
const NODE_W = 168
const NODE_H = 26
const TOP = 34

interface Props {
  net: Net
  t: Trace
  selected: string | null
  off: ReadonlySet<string>
  onSelect: (id: string) => void
}

export function NetworkGraph({ net, t, selected, off, onSelect }: Props) {
  const [hover, setHover] = useState<string | null>(null)
  const depth = net.layers.length
  const sizes = net.sizes
  const rows = Math.max(...sizes)
  const gap = 34
  const H = TOP + rows * gap + 16
  const colX = (layer: number) => NODE_W / 2 + 8 + (layer / depth) * (W - NODE_W - 16)
  const yOf = (layer: number, i: number) => TOP + ((rows - sizes[layer]) * gap) / 2 + i * gap + gap / 2
  const id = (layer: number, i: number) =>
    layer === 0 ? `x${i}` : layer === depth ? `y${i}` : `h${layer}_${i}`
  const pos = new Map<string, { x: number; y: number; layer: number; i: number }>()
  sizes.forEach((n, layer) => { for (let i = 0; i < n; i++) pos.set(id(layer, i), { x: colX(layer), y: yOf(layer, i), layer, i }) })

  const circuitEdges = new Set(t.circuit?.edges ?? [])
  const backupEdges = new Set(t.backup?.edges ?? [])
  const circuitNodes = new Set(t.circuit?.nodes ?? [])
  const backupNodes = new Set(t.backup?.nodes ?? [])
  circuitNodes.add(`y${t.choice}`)

  const attrs = Object.entries(t.edgeAttr).filter(([, a]) => Math.abs(a) > 1e-9)
  const max = Math.max(1e-9, ...attrs.map(([, a]) => Math.abs(a)))
  const faint = attrs.filter(([e, a]) => Math.abs(a) > max * 0.03 && !circuitEdges.has(e) && !backupEdges.has(e))
    .sort((p, q) => Math.abs(q[1]) - Math.abs(p[1])).slice(0, 140)
  const ends = (e: string) => {
    const [l, i, j] = e.split(':').map(Number)
    return [pos.get(id(l, i))!, pos.get(id(l + 1, j))!, id(l, i), id(l + 1, j)] as const
  }
  const curve = (e: string) => {
    const [p, q] = ends(e)
    const x1 = p.x + NODE_W / 2
    const x2 = q.x - NODE_W / 2
    const mx = (x1 + x2) / 2
    return `M${x1},${p.y} C${mx},${p.y} ${mx},${q.y} ${x2},${q.y}`
  }
  const touches = (e: string) => { const [, , a, b] = ends(e); return a === hover || b === hover }
  const dimmed = (e: string) => hover !== null && !touches(e)

  const value = (nid: string) => {
    const p = pos.get(nid)!
    return p.layer === depth ? t.run.probs[p.i] : t.run.acts[p.layer][p.i]
  }
  const scale = t.run.acts.map((a) => Math.max(1e-6, ...a.map(Math.abs)))
  const name = (nid: string) => {
    const p = pos.get(nid)!
    if (p.layer === 0) return net.inputs[p.i].id
    if (p.layer === depth) return net.outputs[p.i].label.toUpperCase()
    return nid
  }
  const label = (nid: string) => net.neurons.find((n) => n.id === nid)?.label ?? ''

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="netgraph" role="img"
      aria-label={`Attribution graph of the network; ${t.circuit?.hidden.length ?? 0} neurons in the circuit`}
      onMouseLeave={() => setHover(null)}>
      {['inputs', 'layer 1 · detectors', 'layer 2 · combine', 'decision'].slice(0, depth + 1).map((h, k) => (
        <text key={h} x={colX(k)} y={16} className="col-head" textAnchor="middle">{h}</text>
      ))}
      <g className="faint">
        {faint.map(([e, a]) => (
          <path key={e} d={curve(e)} className={a > 0 ? 'e pos' : 'e neg'}
            strokeWidth={0.5 + 2.5 * Math.abs(a) / max}
            opacity={dimmed(e) ? 0.04 : hover ? 0.85 : 0.12 + 0.5 * Math.abs(a) / max} />
        ))}
      </g>
      {[...backupEdges].map((e) => (
        <path key={`b${e}`} d={curve(e)} className="e backup" opacity={dimmed(e) ? 0.15 : 0.9}
          strokeWidth={1.2 + 3 * Math.abs(t.edgeAttr[e] ?? 0) / max} />
      ))}
      {[...circuitEdges].map((e) => (
        <g key={`c${e}`} opacity={dimmed(e) ? 0.2 : 1}>
          <path d={curve(e)} className="e circuit" strokeWidth={1.6 + 4 * Math.abs(t.edgeAttr[e] ?? 0) / max} />
          <path d={curve(e)} className="e flow" />
        </g>
      ))}
      {[...pos.keys()].map((nid) => {
        const p = pos.get(nid)!
        const v = value(nid)
        const hidden = p.layer > 0 && p.layer < depth
        const role = circuitNodes.has(nid) ? 'circuit' : backupNodes.has(nid) ? 'backup' : ''
        const fill = p.layer === depth ? v : Math.min(1, Math.abs(v) / scale[p.layer])
        const isOff = off.has(nid)
        return (
          <g key={nid} transform={`translate(${p.x - NODE_W / 2},${p.y - NODE_H / 2})`}
            className={`n ${role}${selected === nid ? ' selected' : ''}${isOff ? ' off' : ''}${hidden ? ' pick' : ''}${v <= 0 && p.layer > 0 && p.layer < depth ? ' quiet' : ''}`}
            onMouseEnter={() => setHover(nid)}
            onClick={hidden ? () => onSelect(nid) : undefined}
            role={hidden ? 'button' : undefined} tabIndex={hidden ? 0 : undefined}
            onKeyDown={hidden ? (ev) => { if (ev.key === 'Enter') onSelect(nid) } : undefined}>
            <title>{`${name(nid)}${hidden ? ` · ${label(nid)}` : ''}: ${v.toFixed(3)}`}</title>
            <rect width={NODE_W} height={NODE_H} rx={3} />
            <rect className="fill" width={Math.max(0, fill) * NODE_W} height={3} y={NODE_H - 3} rx={1} />
            <text x={7} y={11} className="n-id">{name(nid)}</text>
            <text x={NODE_W - 7} y={11} className="n-val" textAnchor="end">{v.toFixed(2)}</text>
            {hidden && <text x={7} y={21} className="n-sub">{label(nid).slice(0, 30)}</text>}
          </g>
        )
      })}
    </svg>
  )
}
