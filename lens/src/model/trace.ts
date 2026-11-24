// Why did the network choose what it chose, rather than what it does when nothing is going on?
//
// Every answer here is relative to a reference: the same network on an uneventful input (for
// the car, the same moment with the road emptied; for an account, a typical clear account).
// This is activation patching, the standard intervention of mechanistic interpretability.
//
// 1. Attribution: how much each neuron and each connection moved the decision's margin (the
//    chosen output over the runner-up) away from the reference. With the ReLU on/off pattern of
//    this input held fixed the network is linear, so these numbers add up along the paths.
// 2. The circuit: the smallest set of hidden neurons that, carrying this input's values while
//    every other one carries the reference's, still makes the same choice. Found
//    greedily, the neuron with the least attribution first, every removal checked by running
//    the network: nothing here is estimated. Its connections are the ones between them.
// 3. The backup route: put the circuit's evidence detectors (first-layer neurons this situation
//    switched on) back to their reference values. If the choice still holds, search again on
//    what is left. That second circuit reaches the same decision from different evidence, the
//    route a reader of the first circuit would miss. Later layers may be shared: two hazards
//    can feed the same "stop" neuron, as two routes in a transaction graph can reach the same
//    collector.
//
// This is the search Lattice runs on AML evidence (explain/circuit.py, explain/routes.py),
// applied to a neural network's own connections instead of transfers.
import { allEdges, edgeId, forward, nodeId, type Ablation, type Net, type Run } from './net'

export interface Route {
  edges: string[]
  nodes: string[]
  hidden: string[]
  margin: number // the choice's margin when only this route carries this input
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
  let gradZ = run.acts[depth].map((_, k) => (k === choice ? 1 : k === runnerUp ? -1 : 0))
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
  base: Ablation // the user's switched-off neurons
  values: number[][] // the reference run's activations
  choice: number
}

function patched(s: Setup, nodes: Iterable<string>, edges: Iterable<string>): Run {
  // Neurons the user switched off stay off (zero); everything patched takes reference values.
  const userOff = new Set(s.base.nodes ?? [])
  const values = s.values.map((layer, l) => layer.map((v, i) =>
    (userOff.has(nodeId(l, i, s.net.layers.length)) ? 0 : v)))
  return forward(s.net, s.x, { nodes: new Set([...userOff, ...nodes]), edges: new Set(edges),
    values })
}

// The circuit as the neurons kept: every other input and neuron carries its reference value.
// Its connections are the ones running between kept neurons, into the chosen output.
function route(s: Setup, kept: Set<string>, frozen: string[]): Route {
  const depth = s.net.layers.length
  const others = candidates(s).filter((n) => !kept.has(n))
  const run = patched(s, [...frozen, ...others], [])
  const isKept = (id: string) =>
    kept.has(id) || id === nodeId(depth, s.choice, depth) || id.startsWith('x')
  const between = allEdges(s.net).filter((e) => {
    const [l, i, j] = parse(e)
    return isKept(nodeId(l, i, depth)) && isKept(nodeId(l + 1, j, depth))
  })
  const edges = connected(s.net, between)
  const nodes = new Set<string>()
  for (const e of edges) {
    const [l, i, j] = parse(e)
    nodes.add(nodeId(l, i, depth))
    nodes.add(nodeId(l + 1, j, depth))
  }
  return { edges, nodes: [...nodes], hidden: [...nodes].filter((n) => n.startsWith('h')),
    margin: marginOf(run, s.choice) }
}

// The hidden neurons the search may patch: not the ones the user switched off. The inputs stay
// as they are: they are the situation being explained.
function candidates(s: Setup): string[] {
  const depth = s.net.layers.length
  const off = s.base.nodes ?? new Set()
  return s.net.sizes.slice(1, -1).flatMap((n, k) =>
    Array.from({ length: n }, (_, i) => nodeId(k + 1, i, depth))).filter((id) => !off.has(id))
}

// Evidence detectors: first-layer neurons this situation switched on, compared with the
// reference. A neuron the situation silenced (a "clear road, go" neuron near a red light) is
// part of the mechanism too, but it is not evidence: it stays as it is in every route.
function detectors(s: Setup, run: Run): string[] {
  const depth = s.net.layers.length
  return candidates(s).filter((n) => n.startsWith('h1_')).filter((n) => {
    const i = Number(n.split('_')[1])
    return run.acts[1][i] > s.values[1][i] + 1e-6
  }).filter(() => depth > 1)
}

// Greedily drop what can be dropped, weakest first, while the choice holds.
function prune(s: Setup, pool: string[], fixed: string[], attr: Record<string, number>): string[] {
  const removed: string[] = []
  const order = [...pool].sort((a, b) => Math.abs(attr[a] ?? 0) - Math.abs(attr[b] ?? 0))
  for (const n of order) {
    removed.push(n)
    if (patched(s, [...fixed, ...removed], []).choice !== s.choice) removed.pop()
  }
  return removed
}

// One route: the fewest evidence detectors that still give the choice (stage 1), then the
// fewest other neurons around them (stage 2). `taken` are detectors earlier routes used.
function search(s: Setup, evidence: string[], taken: string[],
  attr: Record<string, number>): Route | null {
  if (patched(s, taken, []).choice !== s.choice) return null
  const pool = evidence.filter((n) => !taken.includes(n))
  const dropped = prune(s, pool, taken, attr)
  const used = pool.filter((n) => !dropped.includes(n))
  if (!used.length) return null
  const rest = candidates(s).filter((n) => !evidence.includes(n))
  const fixed = [...taken, ...dropped]
  const restDropped = prune(s, rest, fixed, attr)
  const kept = new Set([...used, ...rest.filter((n) => !restDropped.includes(n))])
  const r = route(s, kept, fixed)
  return r.edges.length ? r : null
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

  const s: Setup = { net, x, base, values: ref.acts, choice }
  const evidence = detectors(s, run)
  const circuit = search(s, evidence, [], nodeAttr)
  const first = circuit?.hidden.filter((n) => evidence.includes(n)) ?? []
  const backup = first.length ? search(s, evidence, first, nodeAttr) : null
  return { ...empty, circuit, backup }
}
