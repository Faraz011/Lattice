// Questions a person asks about a decision, answered by running the network.
//
// - What drove it? Take each thing in the input away (set back to the reference), one at a time,
//   and see how much of the decision's margin goes with it, and whether the decision changes.
// - What if? Move one input and decide again.
import { forward, type Ablation, type Net } from './net'
import { marginOf, things } from './trace'

export interface Driver {
  label: string
  inputs: number[]
  effect: number // margin lost when this thing is taken away (negative: it worked against)
  share: number // of the absolute effects, this one's part (0..1)
  without: number // the choice with this thing taken away
}

export function drivers(net: Net, x: number[], reference: number[], base: Ablation): Driver[] {
  const run = forward(net, x, base)
  const full = marginOf(run, run.choice)
  const changed = things(net).filter((t) => t.inputs.some((i) => Math.abs(x[i] - reference[i]) > 1e-9))
  const out = changed.map((t) => {
    const without = x.map((v, i) => (t.inputs.includes(i) ? reference[i] : v))
    const r = forward(net, without, base)
    return { label: t.label, inputs: t.inputs, effect: full - marginOf(r, run.choice), share: 0,
      without: r.choice }
  })
  const total = out.reduce((s, d) => s + Math.abs(d.effect), 0) || 1
  for (const d of out) d.share = Math.abs(d.effect) / total
  return out.sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect))
}

export function whatIf(net: Net, x: number[], base: Ablation, changes: Record<number, number>) {
  const moved = x.map((v, i) => (i in changes ? changes[i] : v))
  return forward(net, moved, base)
}

// The inputs that matter most to this decision, by attribution, for the what-if sliders.
export function levers(net: Net, nodeAttr: Record<string, number>, count = 4): number[] {
  return net.inputs.map((_, i) => i)
    .sort((a, b) => Math.abs(nodeAttr[`x${b}`] ?? 0) - Math.abs(nodeAttr[`x${a}`] ?? 0))
    .slice(0, count)
}
