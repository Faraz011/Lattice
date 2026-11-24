// A small ReLU network exported by `lattice.lens.train`, run in the browser.
//
// Node ids: `x3` is input 3, `h1_4` is neuron 4 of hidden layer 1, `y2` is output 2.
// Edge ids: `${layer}:${i}:${j}`, from node i of `layer` (0 = inputs) to node j of the next.
//
// Switching a node or an edge off: an input takes its average over the training data (zero is
// not neutral for a distance), a hidden neuron goes to zero, which is what "off" means.
// The tracer instead patches in the values from a reference run (`Ablation.values`), the same
// network on an uneventful input: see trace.ts.

export interface Feature {
  id: string
  label: string
  description: string
  low_label: string
}

export interface NeuronInfo {
  id: string
  layer: number
  index: number
  active: number
  dead: boolean
  label: string
  fires_on: { feature: string; corr: number }[]
  pushes: string | null
}

export interface Net {
  name: string
  title: string
  notes: string
  sizes: number[]
  inputs: Feature[]
  outputs: Feature[]
  layers: { W: number[][]; b: number[] }[]
  means: number[][]
  neurons: NeuronInfo[]
  metrics: Record<string, unknown>
  physics?: Record<string, number>
  // Things in the scene, as groups of input ids; the tracer takes a thing away whole.
  groups?: { label: string; inputs: string[] }[]
}

export interface Ablation {
  nodes?: ReadonlySet<string>
  edges?: ReadonlySet<string>
  // What a switched-off node or edge carries, per layer. Absent: inputs at their average,
  // hidden neurons at zero.
  values?: number[][]
}

export interface Run {
  acts: number[][] // every layer's activations; the last is the logits
  probs: number[]
  choice: number
}

export const nodeId = (layer: number, i: number, depth: number): string =>
  layer === 0 ? `x${i}` : layer === depth ? `y${i}` : `h${layer}_${i}`

export const edgeId = (layer: number, i: number, j: number): string => `${layer}:${i}:${j}`

export function softmax(z: number[]): number[] {
  const top = Math.max(...z)
  const e = z.map((v) => Math.exp(v - top))
  const sum = e.reduce((a, b) => a + b, 0)
  return e.map((v) => v / sum)
}

export function argmax(v: number[]): number {
  let best = 0
  for (let i = 1; i < v.length; i++) if (v[i] > v[best]) best = i
  return best
}

// What a node of `layer` is when switched off.
export function baseline(net: Net, layer: number): number[] {
  return layer === 0 ? net.means[0] : net.means[layer].map(() => 0)
}

export function forward(net: Net, x: number[], ablation: Ablation = {}): Run {
  const depth = net.layers.length
  const nodes = ablation.nodes
  const edges = ablation.edges
  const base = (layer: number) => ablation.values?.[layer] ?? baseline(net, layer)
  const off = (layer: number, a: number[]) => {
    if (!nodes || !nodes.size) return a
    const value = base(layer)
    return a.map((v, i) => (nodes.has(nodeId(layer, i, depth)) ? value[i] : v))
  }
  const acts: number[][] = [off(0, x)]
  for (let layer = 0; layer < depth; layer++) {
    const { W, b } = net.layers[layer]
    const a = acts[layer]
    const mean = base(layer)
    const z = W.map((row, j) => {
      let s = b[j]
      for (let i = 0; i < row.length; i++) {
        const v = edges && edges.size && edges.has(edgeId(layer, i, j)) ? mean[i] : a[i]
        s += row[i] * v
      }
      return s
    })
    const out = layer === depth - 1 ? z : z.map((v) => Math.max(v, 0))
    acts.push(layer === depth - 1 ? out : off(layer + 1, out))
  }
  const logits = acts[depth]
  const probs = softmax(logits)
  return { acts, probs, choice: argmax(probs) }
}

export function allEdges(net: Net): string[] {
  const out: string[] = []
  net.layers.forEach(({ W }, layer) =>
    W.forEach((row, j) => row.forEach((_, i) => out.push(edgeId(layer, i, j)))))
  return out
}

export async function loadNet(name: string): Promise<Net> {
  const res = await fetch(`${import.meta.env.BASE_URL}models/${name}.json`)
  if (!res.ok) throw new Error(`Could not load the ${name} model (${res.status}).`)
  return res.json()
}
