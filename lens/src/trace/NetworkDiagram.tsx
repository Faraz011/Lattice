// Every neuron of the network, in columns from inputs to decisions. Connections are drawn by
// how much they pushed this decision; the circuit is solid red, the backup route dashed brass.
// Click a hidden neuron to switch it off, on both devices.
import type { Net } from '../model/net'
import type { Trace } from '../model/trace'

const W = 1000
const ROW = 40
const TOP = 46
const COLS = [250, 450, 690, 860]
const SEAL = '#a3233a'
const BRASS = '#85661c'

interface Props {
  net: Net
  trace: Trace
  off: ReadonlySet<string>
  onToggle: (id: string) => void
}

export function NetworkDiagram({ net, trace, off, onToggle }: Props) {
  const depth = net.layers.length
  const sizes = net.sizes
  // Rows shrink for a tall layer, so the whole network fits a laptop screen.
  const row = Math.min(ROW, 620 / Math.max(...sizes))
  const height = TOP * 2 + Math.max(...sizes) * row
  const yOf = (layer: number, i: number) =>
    TOP + (height - 2 * TOP - (sizes[layer] - 1) * row) / 2 + i * row
  const pos = (layer: number, i: number) => ({ x: COLS[layer], y: yOf(layer, i) })
  const nodeKey = (layer: number, i: number) =>
    layer === 0 ? `x${i}` : layer === depth ? `y${i}` : `h${layer}_${i}`

  const circuit = new Set(trace.circuit?.edges ?? [])
  const backup = new Set(trace.backup?.edges ?? [])
  const inCircuit = new Set(trace.circuit?.hidden ?? [])
  const inBackup = new Set(trace.backup?.hidden ?? [])

  // The strongest connections, so the drawing stays readable.
  const attrs = Object.entries(trace.edgeAttr).filter(([, a]) => Math.abs(a) > 1e-9)
  const max = Math.max(1e-9, ...attrs.map(([, a]) => Math.abs(a)))
  const strong = attrs.filter(([, a]) => Math.abs(a) >= max * 0.04)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 70)
  const line = (id: string) => {
    const [l, i, j] = id.split(':').map(Number)
    return { a: pos(l, i), b: pos(l + 1, j) }
  }
  const neuron = (id: string) => net.neurons.find((n) => n.id === id)
  const actMax = trace.run.acts.map((layer) => Math.max(1e-9, ...layer.map(Math.abs)))

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="diagram" role="img"
      aria-label={`The network: ${sizes.join(', ')} neurons by layer`}>
      {['What it sees', 'Detectors', 'Combined', 'Decision'].map((t, k) => (
        <text key={t} x={COLS[k]} y={22} textAnchor="middle" className="label soft"
          style={{ fontWeight: 700, fontSize: 15 }}>{t}</text>
      ))}
      {strong.map(([id, a]) => {
        const { a: p, b: q } = line(id)
        return <line key={id} x1={p.x} y1={p.y} x2={q.x} y2={q.y}
          stroke={a > 0 ? '#c98a96' : '#8b9bc4'} strokeWidth={0.6 + 3.5 * Math.abs(a) / max}
          opacity={0.75} />
      })}
      {[...backup].map((id) => {
        const { a: p, b: q } = line(id)
        return <line key={`b-${id}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke={BRASS}
          strokeWidth={2.5} strokeDasharray="7 5" />
      })}
      {[...circuit].map((id) => {
        const { a: p, b: q } = line(id)
        return <line key={`c-${id}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke={SEAL} strokeWidth={3} />
      })}

      {net.inputs.map((f, i) => {
        const { x, y } = pos(0, i)
        const v = trace.run.acts[0][i]
        const used = trace.circuit?.nodes.includes(`x${i}`)
        return (
          <g key={f.id}>
            <title>{f.description}</title>
            <text x={x - 66} y={y + 5} textAnchor="end" className={used ? 'label' : 'label soft'}
              style={{ fontWeight: used ? 700 : 400, fontSize: 15 }}>{f.label}</text>
            <rect x={x - 58} y={y - 5} width={50} height={10} fill="#dee6dc" rx={2} />
            <rect x={x - 58} y={y - 5} width={50 * Math.max(0, Math.min(1, v))} height={10}
              fill={used ? SEAL : '#4b5670'} rx={2} />
            <circle cx={x} cy={y} r={5} fill={used ? SEAL : '#1e2942'} />
          </g>
        )
      })}

      {sizes.slice(1, -1).flatMap((n, k) => Array.from({ length: n }, (_, i) => {
        const layer = k + 1
        const id = nodeKey(layer, i)
        const { x, y } = pos(layer, i)
        const info = neuron(id)
        const a = trace.run.acts[layer][i]
        const isOff = off.has(id)
        const ring = inCircuit.has(id) ? SEAL : inBackup.has(id) ? BRASS : '#1e2942'
        const label = info?.label ?? id
        return (
          <g key={id} className="neuron" role="button" tabIndex={0} aria-pressed={isOff}
            aria-label={`${id}, ${label}${isOff ? ', switched off' : ''}. Activation ${a.toFixed(2)}.`}
            onClick={() => onToggle(id)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(id) } }}>
            <title>{`${label}\nActivation ${a.toFixed(2)}. ${isOff ? 'Switched off: click to switch back on.' : 'Click to switch it off.'}`}</title>
            <circle cx={x} cy={y} r={12} fill={isOff ? '#c5cfc4' : '#1e2942'}
              fillOpacity={isOff ? 1 : 0.08 + 0.92 * Math.max(0, a) / actMax[layer]}
              stroke={ring} strokeWidth={inCircuit.has(id) || inBackup.has(id) ? 3.5 : 1.5}
              strokeDasharray={inBackup.has(id) && !inCircuit.has(id) ? '4 3' : undefined} />
            {isOff && <path d={`M${x - 7},${y - 7} L${x + 7},${y + 7} M${x + 7},${y - 7} L${x - 7},${y + 7}`}
              stroke={SEAL} strokeWidth={2.5} />}
            <text x={x + 17} y={y + 5} className={a > 0 && !isOff ? 'label' : 'label soft'}
              style={{ fontSize: 13 }}>{short(label)}</text>
          </g>
        )
      }))}

      {net.outputs.map((o, k) => {
        const { x, y } = pos(depth, k)
        const chosen = k === trace.choice
        const p = trace.run.probs[k]
        return (
          <g key={o.id}>
            <circle cx={x} cy={y} r={chosen ? 15 : 11} fill={chosen ? SEAL : '#f6f8f3'}
              stroke="#1e2942" strokeWidth={1.5} />
            <text x={x + 22} y={y + 5} className="label"
              style={{ fontWeight: chosen ? 700 : 400, fontSize: 16 }}>
              {o.label} {Math.round(p * 100)}%</text>
          </g>
        )
      })}
    </svg>
  )
}

const short = (s: string) => (s.length > 26 ? `${s.slice(0, 25)}…` : s)
