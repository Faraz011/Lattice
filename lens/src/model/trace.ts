// Why did the network choose what it chose, rather than what it does when nothing is going on?
//
// Every answer here is relative to a reference: the same network on an uneventful input (for
// the car, the same moment with the road emptied; for an account, a typical clear account).
// The interventions are activation patching, the standard tool of mechanistic interpretability:
// run the network with some values taken from the reference run, and see if the choice holds.
//
// 1. Attribution: how much each neuron and each connection moved the decision's margin (the
//    chosen output over the runner-up) away from the reference. With the ReLU on/off pattern of
//    this input held fixed the network is linear, so these numbers add up along the paths.
// 2. Routes. A route is a reason the network has for this decision:
//    - its evidence: the fewest things in the input that, with everything else as in the
//      reference, still give the same choice. A thing is a group of inputs taken away whole
//      (the traffic light: its colour and its distance), so no situation is ever invented
//      that could not happen, such as a light with no colour;
//    - its neurons: with only that evidence, the fewest hidden neurons that carry the choice,
//      every other neuron patched to its reference value. A neuron the evidence silences (a
//      "keep going" neuron gone quiet) belongs to the route as much as one it switches on.
//    Every step is checked by running the network: nothing here is estimated.
// 3. The circuit is the first route. The backup route is a second one from the evidence the
//    circuit did not use: the pedestrian, when the circuit was the red light. A reader of the
//    circuit alone would not know it exists; switch the circuit's detectors off and the
//    decision still holds, through it.
//
// This is the search Lattice runs on AML evidence (explain/circuit.py, explain/routes.py),
// applied to a neural network instead of a transaction graph.
import { allEdges, edgeId, forward, nodeId, type Ablation, type Net, type Run } from './net'

export interface Route {
  evidence: string[] // the things in the input this route rests on, e.g. "the traffic light"
  inputs: number[] // their inputs, by index
  edges: string[]
  nodes: string[]
  hidden: string[] // the neurons that carry it
  fired: string[] // of those, first-layer neurons it switches on: the ones a switch can fail
  silenced: string[] // first-layer neurons it quiets, compared with the reference
  combined: string[] // the later-layer neurons it runs through
  margin: number // the choice's margin on this evidence alone, through these neurons alone
}

export interface Trace {
  run: Run
  reference: Run
  choice: number
  runnerUp: number
  margin: number
  nodeAttr: Record<string, number>
  edgeAttr: Record<string, number>
  // null when the network makes the same choice on the reference: nothing to explain.
  circuit: Route | null
  backup: Route | null
}

export function marginOf(run: Run, choice: number): number {
  const z = run.acts[run.acts.length - 1]
  return z[choice] - Math.max(...z.filter((_, k) => k !== choice))
}

const parse = (e: string) => e.split(':').map(Number) as [number, number, number]

export function attribute(net: Net, run: Run, reference: Run, choice: number, runnerUp: number) {
  const depth = net.layers.length
  const nodeAttr: Record<string, number> = {}
  const edgeAttr: Record<string, number> = {}
  // d(margin)/d(pre-activation) of the layer above, walking down from the outputs.
  let gradZ: number[] = run.acts[depth].map((_, k) => (k === choice ? 1 : k === runnerUp ? -1 : 0))
  for (let layer = depth - 1; layer >= 0; layer--) {
    const { W } = net.layers[layer]
    const a = run.acts[layer]
    const ref = reference.acts[layer]
    const gradA = a.map((_, i) => W.reduce((s, row, j) => s + row[i] * gradZ[j], 0))
    a.forEach((v, i) => {
      nodeAttr[nodeId(layer, i, depth)] = (v - ref[i]) * gradA[i]
      W.forEach((row, j) => { edgeAttr[edgeId(layer, i, j)] = (v - ref[i]) * row[i] * gradZ[j] })
    })
    gradZ = gradA.map((g, i) => (layer > 0 && a[i] > 0 ? g : 0))
  }
  return { nodeAttr, edgeAttr }
}

// Keep only connections on some input-to-output path through the kept set.
function connected(net: Net, kept: Iterable<string>): string[] {
  const depth = net.layers.length
  const reach = new Set(net.inputs.map((_, i) => nodeId(0, i, depth)))
  const edges = [...kept].map(parse).sort((a, b) => a[0] - b[0])
  const reachable = edges.filter(([l, i, j]) => {
    if (!reach.has(nodeId(l, i, depth))) return false
    reach.add(nodeId(l + 1, j, depth))
    return true
  })
  const back = new Set(net.outputs.map((_, k) => nodeId(depth, k, depth)))
  const out: string[] = []
  for (const [l, i, j] of [...reachable].reverse()) {
    if (!back.has(nodeId(l + 1, j, depth))) continue
    back.add(nodeId(l, i, depth))
    out.push(edgeId(l, i, j))
  }
  return out.reverse()
}

interface Setup {
  net: Net
  x: number[]
  reference: number[]
  base: Ablation // neurons the user switched off: they stay off (zero) throughout
  choice: number
}

const only = (s: Setup, keep: ReadonlySet<number>) =>
  s.x.map((v, i) => (keep.has(i) ? v : s.reference[i]))

const holds = (s: Setup, x: number[], ablation: Ablation = s.base) =>
  forward(s.net, x, ablation).choice === s.choice

interface Thing { label: string; inputs: number[] }

// The input's things: the model's groups, or each input on its own.
export function things(net: Net): Thing[] {
  const index = new Map(net.inputs.map((f, i) => [f.id, i]))
  if (net.groups?.length) {
    return net.groups.map((g) => ({ label: g.label,
      inputs: g.inputs.map((id) => index.get(id)).filter((i): i is number => i !== undefined) }))
  }
  return net.inputs.map((f, i) => ({ label: f.label, inputs: [i] }))
}

// The fewest of `pool` (things) that alone still give the choice, or null.
function evidence(s: Setup, pool: Thing[], attr: Record<string, number>): Thing[] | null {
  const inputsOf = (ts: Iterable<Thing>) => new Set([...ts].flatMap((t) => t.inputs))
  const keep = new Set(pool)
  if (!holds(s, only(s, inputsOf(keep)))) return null
  const weight = (t: Thing) => t.inputs.reduce((sum, i) => sum + Math.abs(attr[`x${i}`] ?? 0), 0)
  for (const t of [...pool].sort((a, b) => weight(a) - weight(b))) {
    keep.delete(t)
    if (!holds(s, only(s, inputsOf(keep)))) keep.add(t)
  }
  return pool.filter((t) => keep.has(t))
}

// With only `found` as evidence: the fewest hidden neurons that carry the choice.
function carry(s: Setup, found: Thing[], attr: Record<string, number>): Route | null {
  const inputs = found.flatMap((t) => t.inputs).filter((i) => Math.abs(s.x[i] - s.reference[i]) > 1e-9)
  const net = s.net
  const depth = net.layers.length
  const x = only(s, new Set(inputs))
  const off = new Set(s.base.nodes ?? [])
  const run = forward(net, x, s.base)
  const ref = forward(net, s.reference, s.base)
  const values = ref.acts.map((layer, l) => layer.map((v, i) => (off.has(nodeId(l, i, depth)) ? 0 : v)))
  const patch = (nodes: string[]) => forward(net, x, { nodes: new Set([...off, ...nodes]), values })
  const pool = net.sizes.slice(1, -1).flatMap((n, k) =>
    Array.from({ length: n }, (_, i) => nodeId(k + 1, i, depth))).filter((id) => !off.has(id))
  const removed: string[] = []
  const order = [...pool].sort((a, b) => Math.abs(attr[a] ?? 0) - Math.abs(attr[b] ?? 0))
  for (const n of order) {
    removed.push(n)
    if (patch(removed).choice !== s.choice) removed.pop()
  }
  const kept = new Set(pool.filter((n) => !removed.includes(n)))
  const used = new Set(inputs.map((i) => nodeId(0, i, depth)))
  const isKept = (id: string) => kept.has(id) || used.has(id) || id === nodeId(depth, s.choice, depth)
  const edges = connected(net, allEdges(net).filter((e) => {
    const [l, i, j] = parse(e)
    return isKept(nodeId(l, i, depth)) && isKept(nodeId(l + 1, j, depth))
  }))
  const nodes = new Set<string>()
  for (const e of edges) {
    const [l, i, j] = parse(e)
    nodes.add(nodeId(l, i, depth))
    nodes.add(nodeId(l + 1, j, depth))
  }
  const hidden = [...nodes].filter((n) => n.startsWith('h'))
  if (!hidden.length) return null
  const shift = (n: string) => {
    const i = Number(n.split('_')[1])
    return run.acts[1][i] - ref.acts[1][i]
  }
  const detectors = hidden.filter((n) => n.startsWith('h1_'))
  const fired = detectors.filter((n) => shift(n) > 1e-6)
  const silenced = detectors.filter((n) => shift(n) < -1e-6)
  const combined = hidden.filter((n) => !n.startsWith('h1_'))
  return { evidence: found.map((t) => t.label), inputs, edges, nodes: [...nodes], hidden, fired,
    silenced, combined, margin: marginOf(patch(removed), s.choice) }
}

export function trace(net: Net, x: number[], reference: number[], base: Ablation = {}): Trace {
  const run = forward(net, x, base)
  const ref = forward(net, reference, base)
  const choice = run.choice
  const z = run.acts[run.acts.length - 1]
  const runnerUp = z.reduce((best, v, k) =>
    (k !== choice && (best < 0 || v > z[best]) ? k : best), -1)
  const { nodeAttr, edgeAttr } = attribute(net, run, ref, choice, runnerUp)
  const empty = { run, reference: ref, choice, runnerUp, margin: marginOf(run, choice), nodeAttr,
    edgeAttr, circuit: null, backup: null }
  if (ref.choice === choice) return empty

  const s: Setup = { net, x, reference, base, choice }
  const changed = things(net).filter((t) => t.inputs.some((i) => Math.abs(x[i] - reference[i]) > 1e-9))
  const first = evidence(s, changed, nodeAttr)
  const circuit = first ? carry(s, first, nodeAttr) : null
  const rest = changed.filter((t) => !first?.includes(t))
  const second = first && rest.length ? evidence(s, rest, nodeAttr) : null
  const backup = second ? carry(s, second, nodeAttr) : null
  return { ...empty, circuit, backup }
}
