// Studies of one decision, each computed by running the network:
//
// - ablation: switch each important neuron off on its own, and see how much of the decision's
//   margin goes with it and whether the decision flips;
// - logit attribution: how much each last hidden layer neuron pushes the chosen output over
//   the runner-up (the network is linear from there, so these add up exactly);
// - sensitivity: the chosen output's probability as one input sweeps its range, the others
//   held where they are.
import { forward, type Ablation, type Net } from './net'
import { marginOf, type Trace } from './trace'

export interface AblationRow {
  id: string
  role: 'circuit' | 'backup' | 'other'
  margin: number // the decision's margin with this neuron off
  delta: number // margin lost (negative: switching it off helped the decision)
  flips: number | null // the new decision, when it changes
}

export function ablationStudy(net: Net, x: number[], t: Trace, base: Ablation, limit = 12): AblationRow[] {
  const circuit = new Set(t.circuit?.hidden ?? [])
  const backup = new Set(t.backup?.hidden ?? [])
  const off = base.nodes ?? new Set<string>()
  const hidden = net.neurons.filter((n) => !n.dead && !off.has(n.id)).map((n) => n.id)
  const rank = (id: string) => (circuit.has(id) ? 2 : backup.has(id) ? 1 : 0) * 1e6
    + Math.abs(t.nodeAttr[id] ?? 0)
  const picked = hidden.sort((a, b) => rank(b) - rank(a)).slice(0, limit)
  return picked.map((id) => {
    const run = forward(net, x, { nodes: new Set([...off, id]) })
    const margin = marginOf(run, t.choice)
    return { id, role: circuit.has(id) ? 'circuit' : backup.has(id) ? 'backup' : 'other', margin,
      delta: t.margin - margin, flips: run.choice !== t.choice ? run.choice : null }
  })
}

export interface Contribution { id: string; value: number }

export function logitAttribution(net: Net, t: Trace): Contribution[] {
  const last = net.layers[net.layers.length - 1].W
  const acts = t.run.acts[t.run.acts.length - 2]
  return acts.map((a, j) => ({ id: `h${net.layers.length - 1}_${j}`,
    value: a * (last[t.choice][j] - last[t.runnerUp][j]) }))
    .filter((c) => Math.abs(c.value) > 1e-6)
    .sort((p, q) => Math.abs(q.value) - Math.abs(p.value))
}

export interface Sweep { input: number; values: number[]; probs: number[]; now: number }

export function sensitivity(net: Net, x: number[], t: Trace, base: Ablation, count = 3,
  steps = 24): Sweep[] {
  const inputs = net.inputs.map((_, i) => i)
    .sort((a, b) => Math.abs(t.nodeAttr[`x${b}`] ?? 0) - Math.abs(t.nodeAttr[`x${a}`] ?? 0))
    .slice(0, count)
  return inputs.map((i) => {
    const values = Array.from({ length: steps + 1 }, (_, k) => k / steps)
    const probs = values.map((v) => {
      const moved = [...x]
      moved[i] = v
      return forward(net, moved, base).probs[t.choice]
    })
    return { input: i, values, probs, now: x[i] }
  })
}

// Every hidden neuron's activation, in layer order: one column of the activity raster.
export function hiddenActivity(t: Trace): number[] {
  return t.run.acts.slice(1, -1).flat()
}
