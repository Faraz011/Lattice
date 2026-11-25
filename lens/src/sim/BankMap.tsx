// The bank's accounts on a real map of Europe, at their home cities. Transfers fly between them
// as arcs; an account takes the colour of the network's verdict, and a frozen one turns into a
// square. Click an account to trace its decision on the other device.
import maplibregl, { type GeoJSONSource, type Map as MapLibre } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef } from 'react'

import type { Bank, Episode, EpisodeAccount } from './aml'

const STYLE = 'https://tiles.openfreemap.org/styles/positron'
const RECENT = 14 // transfers drawn as arcs

interface Props {
  bank: Bank
  episode: Episode
  version: number // bumps whenever the bank changes
  // The planted cases, shown to the audience on request: the network never sees them.
  answerKey: Map<string, { category: string }> | null
  onFocus: (account: string) => void
}

type Point = [number, number]

// A curved path between two places, bowed to the side, so overlapping flows stay apart.
function arc(a: Point, b: Point, steps = 24): Point[] {
  const mid: Point = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const bow = 0.18
  const ctrl: Point = [mid[0] - dy * bow, mid[1] + dx * bow]
  return Array.from({ length: steps + 1 }, (_, k) => {
    const t = k / steps
    const u = 1 - t
    return [u * u * a[0] + 2 * u * t * ctrl[0] + t * t * b[0],
      u * u * a[1] + 2 * u * t * ctrl[1] + t * t * b[1]] as Point
  })
}

export function BankMap({ bank, episode, version, answerKey, onFocus }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibre | null>(null)
  const ready = useRef(false)
  const focus = useRef(onFocus)
  focus.current = onFocus
  const places = useRef(new Map<string, EpisodeAccount>(episode.accounts.map((a) => [a.id, a])))

  useEffect(() => {
    if (!container.current) return
    const m = new maplibregl.Map({
      container: container.current, style: STYLE, bounds: [[-11, 37], [23, 61]],
      fitBoundsOptions: { padding: 30 }, pitch: 20, attributionControl: { compact: true },
      canvasContextAttributes: { preserveDrawingBuffer: true }, dragRotate: false,
    })
    map.current = m
    m.on('load', () => {
      const empty = { type: 'FeatureCollection' as const, features: [] }
      for (const id of ['flows', 'accounts', 'mover']) m.addSource(id, { type: 'geojson', data: empty })
      m.addLayer({ id: 'flows', type: 'line', source: 'flows',
        layout: { 'line-cap': 'round' },
        paint: { 'line-color': ['case', ['get', 'blocked'], '#a3233a', '#3a4a78'],
          'line-width': ['interpolate', ['linear'], ['get', 'age'], 0, 3.2, 1, 1],
          'line-opacity': ['interpolate', ['linear'], ['get', 'age'], 0, 0.95, 1, 0.18],
          'line-dasharray': [2, 1.5] } })
      m.addLayer({ id: 'key', type: 'circle', source: 'accounts', filter: ['has', 'key'],
        paint: { 'circle-radius': 12, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-width': 2,
          'circle-stroke-color': ['match', ['get', 'key'], 'planted', '#a3233a', '#2f6b4f'] } })
      m.addLayer({ id: 'focus', type: 'circle', source: 'accounts', filter: ['get', 'focus'],
        paint: { 'circle-radius': 15, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-width': 3,
          'circle-stroke-color': '#85661c' } })
      m.addLayer({ id: 'accounts', type: 'circle', source: 'accounts',
        paint: {
          'circle-radius': ['case', ['==', ['get', 'kind'], 'person'], 5.5, 8],
          'circle-color': ['match', ['get', 'state'], 'frozen', '#a3233a', 'flagged', '#d9536a',
            ['case', ['==', ['get', 'kind'], 'person'], '#f6f8f3', '#c9d4e8']],
          'circle-stroke-color': ['match', ['get', 'state'], 'frozen', '#ffffff', '#1e2942'],
          'circle-stroke-width': ['match', ['get', 'state'], 'frozen', 3, 1.4],
        } })
      m.addLayer({ id: 'labels', type: 'symbol', source: 'accounts',
        filter: ['any', ['get', 'focus'], ['!=', ['get', 'kind'], 'person']],
        layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-offset': [0, 1.3],
          'text-anchor': 'top', 'text-font': ['Noto Sans Regular'] },
        paint: { 'text-color': '#1e2942', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 } })
      m.addLayer({ id: 'mover', type: 'circle', source: 'mover',
        paint: { 'circle-radius': 7, 'circle-color': ['case', ['get', 'blocked'], '#a3233a', '#e3a21a'],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } })
      m.on('click', 'accounts', (e) => {
        const id = e.features?.[0]?.properties?.id
        if (typeof id === 'string') focus.current(id)
      })
      m.on('mouseenter', 'accounts', () => { m.getCanvas().style.cursor = 'pointer' })
      m.on('mouseleave', 'accounts', () => { m.getCanvas().style.cursor = '' })
      ready.current = true
      redraw()
    })
    return () => { m.remove(); map.current = null; ready.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [episode])

  // The moving dot: the newest transfer, flown over 0.9 s.
  const flight = useRef<{ path: Point[]; blocked: boolean; start: number } | null>(null)

  function redraw() {
    const m = map.current
    if (!m || !ready.current) return
    const place = (id: string): Point => { const a = places.current.get(id)!; return [a.lng, a.lat] }
    const shown = episode.steps.slice(Math.max(0, bank.step - RECENT), bank.step)
    ;(m.getSource('flows') as GeoJSONSource).setData({ type: 'FeatureCollection',
      features: shown.map((s, i) => ({ type: 'Feature', properties: {
        blocked: bank.blocked.has(s.tx.id), age: 1 - (i + 1) / shown.length },
      geometry: { type: 'LineString', coordinates: arc(place(s.tx.src), place(s.tx.dst)) } })) })
    ;(m.getSource('accounts') as GeoJSONSource).setData({ type: 'FeatureCollection',
      features: episode.accounts.map((a) => {
        const v = bank.verdicts.get(a.id)
        const state = bank.frozen.has(a.id) ? 'frozen' : v && v.choice !== 0 ? 'flagged' : 'clear'
        const key = answerKey?.get(a.id)?.category
        return { type: 'Feature', properties: { id: a.id, kind: a.kind, state,
          focus: a.id === bank.focus, ...(key ? { key } : {}),
          label: a.kind === 'person' ? `${a.owner}, ${a.city}` : a.owner },
        geometry: { type: 'Point', coordinates: [a.lng, a.lat] } }
      }) })
    const last = bank.step > 0 ? episode.steps[bank.step - 1] : null
    if (last) {
      flight.current = { path: arc(place(last.tx.src), place(last.tx.dst), 60),
        blocked: bank.blocked.has(last.tx.id), start: performance.now() }
    }
  }

  useEffect(redraw)

  useEffect(() => {
    let raf = 0
    const tick = () => {
      const m = map.current
      const f = flight.current
      if (m && ready.current && f) {
        const t = Math.min(1, (performance.now() - f.start) / 900)
        const at = f.path[Math.round(t * (f.path.length - 1))]
        ;(m.getSource('mover') as GeoJSONSource).setData({ type: 'FeatureCollection',
          features: t < 1 ? [{ type: 'Feature', properties: { blocked: f.blocked },
            geometry: { type: 'Point', coordinates: at } }] : [] })
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  return <div ref={container} className="bank-map" role="img" data-version={version}
    aria-label="A map of Europe with the bank's accounts at their cities and recent transfers" />
}
