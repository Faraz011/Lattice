// The evidence graph: every edge the agents' tool calls returned. Once a verdict exists, the
// circuit is drawn thick and numbered, supporting evidence in ink, and everything else faded.
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { useEffect, useMemo, useRef } from 'react'

import { money, shortId } from '../ids'
import type { CircuitReport, EdgeDetail, Evidence, EvidenceEdge } from '../types'

export const INK = '#1e2942'
export const SEAL = '#a3233a'
export const FINE = '#98a69e'
export const BRASS = '#85661c'

export interface GraphOptions {
  seed?: string
  removed?: ReadonlySet<string>
}

type Edge = EvidenceEdge | (EdgeDetail & { sources?: string[] })

/** The circuit's edges in time order, numbered from 1: the order money moved. */
export function circuitOrder(report: CircuitReport | null): Map<string, number> {
  const order = new Map<string, number>()
  if (!report || report.circuit.status !== 'circuit') return order
  const byId = new Map(report.edges.map((e) => [e.id, e]))
  const sorted = [...report.circuit.circuit_edges].sort((a, b) =>
    (byId.get(a)?.ts ?? '').localeCompare(byId.get(b)?.ts ?? '') || a.localeCompare(b))
  sorted.forEach((id, i) => order.set(id, i + 1))
  return order
}

export function graphElements(
  evidence: Evidence | null, report: CircuitReport | null, options: GraphOptions = {},
): ElementDefinition[] {
  const edges = new Map<string, Edge>()
  for (const e of evidence?.edges ?? []) edges.set(e.id, e)
  // Edges the report names are always drawn, even if the evidence view is capped.
  for (const e of report?.edges ?? []) if (!edges.has(e.id)) edges.set(e.id, e)

  const kinds = new Map<string, string>()
  for (const n of evidence?.nodes ?? []) {
    kinds.set(n.id, n.kind === 'device' ? 'device' : (n.account_kind ?? 'person'))
  }
  const nodeIds = new Set<string>(options.seed ? [options.seed] : [])
  for (const e of edges.values()) { nodeIds.add(e.src); nodeIds.add(e.dst) }

  const circuit = new Set(report?.circuit.circuit_edges ?? [])
  const supporting = new Set(report?.circuit.supporting_edges ?? [])
  const order = circuitOrder(report)
  const judged = Boolean(report && report.circuit.status === 'circuit')

  const nodes: ElementDefinition[] = [...nodeIds].map((id) => {
    const kind = kinds.get(id) ?? (id.startsWith('dev_') ? 'device' : 'person')
    const classes = [kind === 'device' ? 'device' : 'account', `kind-${kind}`]
    if (id === options.seed) classes.push('seed')
    let label = kind === 'person' || kind === 'device' ? shortId(id) : `${shortId(id)} (${kind})`
    if (id === options.seed) label = `${label}, alerted`
    return { group: 'nodes', data: { id, label, kind }, classes: classes.join(' ') }
  })

  const links: ElementDefinition[] = [...edges.values()].map((e) => {
    const classes = [e.kind === 'device_link' ? 'device-link' : 'transfer']
    let label = e.kind === 'transfer' ? money(e.amount) : ''
    if (judged) {
      if (circuit.has(e.id)) {
        classes.push('circuit')
        label = `${order.get(e.id)}. ${label || 'shared device'}`
      } else if (supporting.has(e.id)) {
        classes.push('supporting')
      } else {
        classes.push('context')
        label = ''
      }
    }
    if (options.removed?.has(e.id)) classes.push('removed')
    return {
      group: 'edges',
      data: { id: e.id, source: e.src, target: e.dst, label },
      classes: classes.join(' '),
    }
  })
  return [...nodes, ...links]
}

const STYLE: cytoscape.StylesheetJson = [
  { selector: 'node', style: {
    'background-color': INK, width: 10, height: 10, label: 'data(label)',
    'font-family': 'Public Sans, system-ui, sans-serif', 'font-size': 11, color: INK,
    'text-valign': 'bottom', 'text-margin-y': 4, 'text-opacity': 0.8,
  } },
  { selector: 'node.device', style: { shape: 'round-rectangle', 'background-color': '#ffffff',
    'border-width': 1.5, 'border-color': INK } },
  { selector: 'node.kind-mixer, node.kind-exchange', style: { shape: 'diamond', width: 14,
    height: 14 } },
  { selector: 'node.seed', style: { width: 16, height: 16, 'border-width': 3,
    'border-color': '#edf1ea', 'outline-width': 1.5, 'outline-color': INK,
    'font-weight': 'bold', 'text-opacity': 1 } as cytoscape.Css.Node },
  { selector: 'edge', style: {
    width: 1.2, 'line-color': INK, 'target-arrow-color': INK, 'target-arrow-shape': 'triangle',
    'arrow-scale': 0.8, 'curve-style': 'bezier', label: 'data(label)', 'font-size': 10,
    'font-family': 'Public Sans, system-ui, sans-serif', color: INK, 'text-rotation': 'autorotate',
    'text-background-color': '#edf1ea', 'text-background-opacity': 0.9,
    'text-background-padding': '1px', opacity: 0.85,
  } },
  { selector: 'edge.device-link', style: { 'line-style': 'dashed', 'target-arrow-shape': 'none',
    'line-dash-pattern': [3, 3] } },
  { selector: 'edge.context', style: { 'line-color': FINE, 'target-arrow-color': FINE,
    opacity: 0.35, width: 0.8 } },
  { selector: 'edge.supporting', style: { width: 2, opacity: 0.9 } },
  { selector: 'edge.circuit', style: {
    width: 5, 'line-color': SEAL, 'target-arrow-color': SEAL, opacity: 1, 'font-size': 12,
    'font-weight': 'bold', color: SEAL, 'z-index': 10, 'arrow-scale': 1,
  } },
  { selector: 'edge.removed', style: { 'line-style': 'dotted', opacity: 0.45,
    'line-dash-pattern': [2, 4] } },
  { selector: ':selected', style: { 'overlay-color': BRASS, 'overlay-opacity': 0.25,
    'overlay-padding': 6 } as cytoscape.Css.Node },
  { selector: '.focus', style: { 'overlay-color': BRASS, 'overlay-opacity': 0.35,
    'overlay-padding': 8 } as cytoscape.Css.Node },
]

interface Props {
  evidence: Evidence | null
  report: CircuitReport | null
  seed?: string
  removed?: ReadonlySet<string>
  focusId?: string | null
  onSelect: (id: string | null) => void
}

export function GraphView({ evidence, report, seed, removed, focusId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const select = useRef(onSelect)
  useEffect(() => { select.current = onSelect }, [onSelect])

  const elements = useMemo(() => graphElements(evidence, report, { seed, removed }),
    [evidence, report, seed, removed])

  useEffect(() => {
    if (!container.current) return
    const instance = cytoscape({ container: container.current, style: STYLE,
      minZoom: 0.2, maxZoom: 3, wheelSensitivity: 0.3 })
    instance.on('tap', 'edge, node', (e) => select.current(e.target.id()))
    instance.on('tap', (e) => { if (e.target === instance) select.current(null) })
    cy.current = instance
    return () => { instance.destroy(); cy.current = null }
  }, [])

  useEffect(() => {
    const instance = cy.current
    if (!instance) return
    const wanted = new Set(elements.map((e) => e.data.id as string))
    const fresh = instance.nodes().length <= 1  // nothing laid out yet: place from scratch
    let grew = false
    instance.batch(() => {
      instance.elements().filter((e) => !wanted.has(e.id())).remove()
      for (const element of elements) {
        const existing = instance.getElementById(element.data.id as string)
        if (existing.nonempty()) {
          existing.data(element.data)
          existing.classes(element.classes as string)
          continue
        }
        if (element.group === 'nodes') {
          // Start new accounts next to a neighbour already on screen, so the layout settles
          // around what the viewer has been watching.
          const anchor = elements.find((e) => e.group === 'edges'
            && (e.data.source === element.data.id || e.data.target === element.data.id))
          const other = anchor && (anchor.data.source === element.data.id
            ? anchor.data.target : anchor.data.source)
          const near = other ? instance.getElementById(other as string) : null
          const at = near?.nonempty() ? near.position() : { x: 0, y: 0 }
          instance.add({ ...element, position: { x: at.x + Math.random() * 40 - 20,
            y: at.y + Math.random() * 40 - 20 } })
        } else {
          instance.add(element)
        }
        grew = true
      }
    })
    if (grew) {
      instance.layout({ name: 'cose', animate: false, randomize: fresh, fit: true, padding: 40,
        nodeRepulsion: () => 40000, idealEdgeLength: () => 120, nodeOverlap: 30,
        componentSpacing: 120 } as cytoscape.LayoutOptions).run()
    }
  }, [elements])

  useEffect(() => {
    const instance = cy.current
    if (!instance) return
    instance.elements().removeClass('focus')
    if (!focusId) return
    const target = instance.getElementById(focusId)
    if (target.empty()) return
    target.addClass('focus')
    instance.animate({ center: { eles: target }, duration: 300 })
  }, [focusId, elements])

  const count = evidence?.edges.length ?? 0
  return (
    <div className="graph">
      <div ref={container} className="graph-canvas" role="img"
        aria-label={`Evidence graph with ${count} edges`} />
      {count === 0 && <p className="graph-empty">Edges appear here as the agents query the
        graph.</p>}
    </div>
  )
}
