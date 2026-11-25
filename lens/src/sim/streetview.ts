// Google Street View along the car's route, through the Map Tiles API (VITE_GOOGLE_MAPS_KEY).
//
// As the car drives, the stretch of road ahead is sampled every few metres and Google is asked
// which panorama is nearest each point. Each new panorama's metadata (exact position, the
// compass heading at its centre, image size, credits) is fetched once, and only the tiles the
// camera looks at are downloaded: about 15 per panorama instead of the 128 of a whole one.
// Nothing is stored beyond this page; Google's terms allow no other caching.
import type { RouteMap } from './driving'
import { poseAt } from './geo'

export const STREET_KEY = (import.meta.env.VITE_GOOGLE_MAPS_KEY as string | undefined) ?? ''
const API = 'https://tile.googleapis.com/v1'
const SPACING = 8 // metres between points asked about
const AHEAD = 260 // metres of road kept resolved ahead of the car
const RADIUS = 20 // a panorama further than this from the road is not on it

export interface Pano {
  id: string
  s: number // metres along the route
  lat: number
  lng: number
  heading: number // compass heading at the centre of the image
  width: number // full image size, pixels
  height: number
  tile: number // tile size, pixels
  copyright: string
  date: string
}

interface Session { id: string; tile: number }

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) })
  if (!r.ok) throw new Error(`Street View ${r.status}: ${(await r.text()).slice(0, 200)}`)
  return r.json()
}

export class PanoTrack {
  private session: Session | null = null
  private asked = new Set<number>() // sample indices already asked about
  private known = new Map<string, Pano>()
  private busy = false
  readonly panos: Pano[] = [] // sorted by s
  error: string | null = null

  private map: RouteMap

  constructor(map: RouteMap) {
    this.map = map
  }

  async start(): Promise<void> {
    const s = await post<{ session: string; tileWidth: number }>(
      `${API}/createSession?key=${STREET_KEY}`,
      { mapType: 'streetview', language: 'en-GB', region: 'GB' })
    this.session = { id: s.session, tile: s.tileWidth }
  }

  tileUrl(pano: Pano, zoom: number, x: number, y: number): string {
    return `${API}/streetview/tiles/${zoom}/${x}/${y}?session=${this.session?.id}&key=${STREET_KEY}` +
      `&panoId=${encodeURIComponent(pano.id)}`
  }

  // The panorama the car is at or has just passed, and the next one, for position `s`.
  around(s: number): { here: Pano | null; next: Pano | null } {
    const L = this.map.length_m
    const at = ((s % L) + L) % L
    let here: Pano | null = null
    let next: Pano | null = null
    for (const p of this.panos) {
      if (p.s <= at) here = p
      else { next = p; break }
    }
    return { here: here ?? this.panos[this.panos.length - 1] ?? null, next: next ?? this.panos[0] ?? null }
  }

  // Resolve the road ahead of `s`. Call often: it does nothing while a request is out.
  async ahead(s: number): Promise<void> {
    if (this.busy || !this.session) return
    const L = this.map.length_m
    const todo: number[] = []
    for (let d = -24; d <= AHEAD; d += SPACING) {
      const k = Math.floor((((s + d) % L) + L) % L / SPACING)
      if (!this.asked.has(k)) todo.push(k)
    }
    if (!todo.length) return
    this.busy = true
    try {
      const batch = todo.slice(0, 60)
      const points = batch.map((k) => poseAt(this.map, k * SPACING))
      const found = await post<{ panoIds: string[] }>(
        `${API}/streetview/panoIds?session=${this.session.id}&key=${STREET_KEY}`,
        { locations: points.map((p) => ({ lat: p.lat, lng: p.lng })), radius: RADIUS })
      batch.forEach((k) => this.asked.add(k))
      const fresh = [...new Set(found.panoIds.filter((id) => id && !this.known.has(id)))]
      await Promise.all(fresh.map(async (id) => {
        const i = found.panoIds.indexOf(id)
        const m = await this.metadata(id)
        if (!m) return
        const pano = { ...m, s: this.project(m.lat, m.lng, batch[i] * SPACING) }
        this.known.set(id, pano)
        this.panos.push(pano)
      }))
      this.panos.sort((a, b) => a.s - b.s)
      this.error = null
    } catch (e) {
      this.error = (e as Error).message
    } finally {
      this.busy = false
    }
  }

  private async metadata(id: string): Promise<Omit<Pano, 's'> | null> {
    const r = await fetch(`${API}/streetview/metadata?session=${this.session?.id}&key=${STREET_KEY}` +
      `&panoId=${encodeURIComponent(id)}`)
    if (!r.ok) return null
    const m = await r.json()
    return { id, lat: m.lat, lng: m.lng, heading: m.heading ?? 0, width: m.imageWidth,
      height: m.imageHeight, tile: m.tileWidth ?? this.session?.tile ?? 512,
      copyright: m.copyright ?? '© Google', date: m.date ?? '' }
  }

  // Where along the route a panorama stands: the nearest route point within 40 m of the point
  // that found it.
  private project(lat: number, lng: number, near: number): number {
    let best = near
    let bestD = Infinity
    for (let d = -40; d <= 40; d += 1) {
      const p = poseAt(this.map, near + d)
      const dx = (p.lng - lng) * 111_320 * Math.cos((lat * Math.PI) / 180)
      const dy = (p.lat - lat) * 110_540
      const dist = dx * dx + dy * dy
      if (dist < bestD) { bestD = dist; best = near + d }
    }
    const L = this.map.length_m
    return ((best % L) + L) % L
  }
}

// Which tiles of a panorama cover a view: columns around a compass bearing, rows around the
// horizon. Zoom 4 is sharp at full screen (a whole panorama would be 16 x 8 tiles).
export interface Patch {
  zoom: number
  cols: number[] // in order, left to right, wrapping around
  rows: number[]
  across: number // tiles across the whole panorama at this zoom
  down: number
  startBearing: number // compass bearing of the patch's left edge
  spanDeg: number // degrees the patch covers across
  topDeg: number // degrees from straight up to the patch's top edge
  heightDeg: number
}

export function patchFor(p: Pano, bearing: number, halfWidthDeg: number, zoom = 4): Patch {
  const maxZoom = Math.ceil(Math.log2(p.width / p.tile))
  const scale = 2 ** (maxZoom - zoom)
  const w = p.width / scale
  const h = p.height / scale
  const across = Math.ceil(w / p.tile)
  const down = Math.ceil(h / p.tile)
  const degPerTile = (p.tile / w) * 360
  // Image x for a bearing: the image centre is the panorama's heading.
  const xOf = (b: number) => ((((b - p.heading) / 360 + 0.5) % 1) + 1) % 1 * w
  const first = Math.floor(xOf(bearing - halfWidthDeg) / p.tile)
  const count = Math.min(across, Math.ceil((2 * halfWidthDeg) / degPerTile) + 2)
  const cols = Array.from({ length: count }, (_, i) => (first + i) % across)
  // Rows: from 25 degrees above the horizon to 40 below.
  const rowOf = (deg: number) => Math.floor(((deg / 180) * h) / p.tile)
  const r0 = Math.max(0, rowOf(90 - 25))
  const r1 = Math.min(down - 1, rowOf(90 + 40))
  const rows = Array.from({ length: r1 - r0 + 1 }, (_, i) => r0 + i)
  const startBearing = p.heading + ((first * p.tile) / w - 0.5) * 360
  return { zoom, cols, rows, across, down, startBearing, spanDeg: count * degPerTile,
    topDeg: (r0 * p.tile / h) * 180, heightDeg: (rows.length * p.tile / h) * 180 }
}
