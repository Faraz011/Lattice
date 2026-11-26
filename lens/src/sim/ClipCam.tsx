// The car's front camera as one real dashcam drive, played like video. lattice.lens.mapillary
// found the longest runs of a single Mapillary sequence along the route with a frame every
// 0.6 to 1 m (london-drives.json); the car is kept on that stretch, and the frame shown is the
// one taken where the car is, blended into the next by how far the car is between the two. So
// the picture moves exactly as fast as the car: it stops at a red light when the car's network
// stops, and pulls away when it pulls away.
//
// Frames are drawn on a canvas, which swaps images without the flicker of changing an <img>.
// Only the stretch around the car is kept in memory; the browser's cache holds the rest.
import { useEffect, useRef, useState, type RefObject } from 'react'

import { between, type Colour, type Physics, type RouteMap, type World } from './driving'
import { poseAt } from './geo'
import { MAPILLARY_TOKEN, photoBoxes, simMarkers, type Detected } from './MapillaryCam'
import { drawBoxes, seen } from './perception'

export interface DriveFrame { id: string; s: number; angle: number; t: number; objects?: Detected[] }
export interface Drive {
  seq: string; start: number; end: number; seconds: number; by: string; date: string
  hfov?: number // degrees across the camera's full frame
  frames: DriveFrame[]
}

export async function loadDrives(): Promise<Drive[]> {
  if (!MAPILLARY_TOKEN) return []
  const r = await fetch(`${import.meta.env.BASE_URL}maps/london-drives.json`)
  if (!r.ok) return []
  return ((await r.json()) as { drives: Drive[] }).drives.filter((d) => d.frames.length > 1)
}

const AHEAD = 70 // frames loaded ahead of the car: about 50 m
const BEHIND = 12 // frames kept behind it
const BATCH = 35 // frame ids per request for image addresses
const PUSH = 0.014 // how much nearer the next frame's scene is: a push-in as the car moves up
// The drives were filmed on a wide lens from the top deck of a bus. Shown as a dashcam sees:
// cropped in to a dashcam's narrower view, which drops the bus's window frame and the steep
// view down onto the road, with the horizon where a car's camera has it and the car's bonnet
// along the foot of the picture.
const CROP = 1.42 // how far in from the photo's own view
const SOURCE_HORIZON = 0.52 // where the horizon is in the photos, as a fraction of the height
const HORIZON = 0.47 // and where a dashcam has it

interface Props {
  world: RefObject<World>
  map: RouteMap
  drive: Drive
  forced: RefObject<Map<number, Colour>>
  tick: number
  physics: Physics
  onFail: (why: string) => void
}

export function ClipCam({ world, map, drive, forced, tick, physics, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const plate = useRef<HTMLDivElement>(null)
  const boxes = useRef<HTMLDivElement>(null)
  const markers = useRef<HTMLDivElement>(null)
  const [progress, setProgress] = useState('')
  const failed = useRef(onFail)
  failed.current = onFail

  useEffect(() => {
    const frames = drive.frames
    const urls = new Map<string, string>()
    const images = new Map<string, HTMLImageElement>() // decoded and ready to draw
    const asked = new Set<string>()
    const order = new Map(frames.map((f, k) => [f.id, k]))
    let alive = true
    let raf = 0
    let errors = 0
    let lastProgress = ''

    const indexAt = (s: number) => {
      let lo = 0
      let hi = frames.length - 1
      if (s <= frames[0].s) return 0
      if (s >= frames[hi].s) return hi
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1
        if (frames[mid].s <= s) lo = mid
        else hi = mid
      }
      return lo
    }

    // Ready once loaded: decoded off the main thread where the browser does so promptly, and
    // drawn as it is otherwise (a background tab may hold decode() back indefinitely).
    const loading = new Set<string>()
    const load = (f: DriveFrame) => {
      const u = urls.get(f.id)
      if (!u || images.has(f.id) || loading.has(f.id)) return
      loading.add(f.id)
      const img = new Image()
      img.decoding = 'async'
      const ready = () => {
        if (!alive || !loading.delete(f.id)) return
        const j = order.get(f.id) ?? -1
        if (j >= lastIndex - BEHIND && j <= lastIndex + AHEAD + BEHIND) images.set(f.id, img)
      }
      img.onload = () => {
        img.decode().then(ready, ready)
        window.setTimeout(ready, 300)
      }
      img.onerror = () => loading.delete(f.id)
      img.src = u
    }

    // Image addresses expire, so they are asked for as the car nears them, a batch at a time.
    const prefetch = async (from: number) => {
      const want = frames.slice(from, from + AHEAD).filter((f) => !asked.has(f.id)).slice(0, BATCH)
      if (want.length < BATCH / 3 && from + AHEAD < frames.length) return
      if (!want.length) return
      want.forEach((f) => asked.add(f.id))
      try {
        const r = await fetch(`https://graph.mapillary.com/?ids=${want.map((f) => f.id).join(',')}` +
          `&fields=thumb_1024_url&access_token=${encodeURIComponent(MAPILLARY_TOKEN)}`)
        if (!r.ok) throw new Error(`Mapillary ${r.status}: ${(await r.text()).slice(0, 160)}`)
        const got = await r.json() as Record<string, { thumb_1024_url?: string }>
        for (const f of want) {
          const u = got[f.id]?.thumb_1024_url
          if (u) urls.set(f.id, u)
        }
        errors = 0
        keep(Math.max(0, lastIndex))
      } catch (e) {
        want.forEach((f) => asked.delete(f.id))
        if (++errors >= 3 && !images.size) failed.current((e as Error).message)
      }
    }

    // Load what is near the car in order of nearness; let go of the rest.
    const keep = (i: number) => {
      for (let k = 0; k < AHEAD; k++) {
        const f = frames[i + k]
        if (f) load(f)
      }
      for (const id of images.keys()) {
        const j = order.get(id) ?? -1
        if (j < i - BEHIND || j > i + AHEAD + BEHIND) images.delete(id)
      }
    }
    let lastIndex = -1
    let sizeKey = ''
    if (import.meta.env.DEV) {
      Object.assign(window, { lensClip: { images, urls, frames, index: () => lastIndex } })
    }
    const draw = () => {
      raf = requestAnimationFrame(draw)
      const w = world.current
      const el = host.current
      const cv = canvas.current
      if (!w || !el || !cv || !alive) return
      const W = el.clientWidth
      const H = el.clientHeight
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      const key = `${W}x${H}x${dpr}`
      if (key !== sizeKey) {
        sizeKey = key
        cv.width = Math.round(W * dpr)
        cv.height = Math.round(H * dpr)
      }
      el.classList.toggle('night', w.night)
      el.classList.toggle('rain', w.rain)

      const now = performance.now()
      const alpha = Math.min(1, (now - (w.tickAt ?? now)) / (tick * 1000))
      const carS = between(w.car.prev, w.car.at, alpha, w.length)
      const i = indexAt(carS)
      if (i !== lastIndex) {
        // Back to the start of the stretch: a short fade, not a hard cut.
        if (lastIndex - i > 20) cv.animate([{ opacity: 0.15 }, { opacity: 1 }], { duration: 450, easing: 'ease-out' })
        lastIndex = i
        void prefetch(i)
        keep(i)
      }
      const here = frames[i]
      const next = frames[i + 1]
      const t = next ? Math.max(0, Math.min(1, (carS - here.s) / Math.max(0.05, next.s - here.s))) : 0

      // The frame to draw under: this one, or the nearest one before it that is ready.
      let base: DriveFrame | null = null
      for (let k = i; k >= Math.max(0, i - BEHIND); k--) {
        if (images.has(frames[k].id)) { base = frames[k]; break }
      }
      const over = base === here && next && images.has(next.id) ? next : null

      const ctx = cv.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      if (!base) { ctx.fillStyle = '#1d2128'; ctx.fillRect(0, 0, W, H); return }

      const bearing = poseAt(map, carS, 12).bearing
      const hfov = drive.hfov ?? 89
      const rectFor = (f: DriveFrame, zoom: number) => {
        const img = images.get(f.id)!
        const k = Math.max(W / img.naturalWidth, H / img.naturalHeight) * zoom * CROP
        const dw = img.naturalWidth * k
        const dh = img.naturalHeight * k
        const fpx = (dw / 2) / Math.tan((hfov / 2) * (Math.PI / 180))
        const diff = ((f.angle - bearing + 540) % 360) - 180
        const pan = Math.max(-0.1 * W, Math.min(0.1 * W, -fpx * Math.tan((diff * Math.PI) / 180)))
        return { img, x: W / 2 - dw / 2 + pan, y: H * HORIZON - dh * SOURCE_HORIZON, w: dw, h: dh, fpx }
      }
      const a = rectFor(base, 1.02 * (1 + PUSH * (base === here ? t : 1)))
      ctx.globalAlpha = 1
      ctx.drawImage(a.img, a.x, a.y, a.w, a.h)
      let shown = a
      let shownFrame = base
      if (over) {
        const b = rectFor(over, 1.02 * (1 - PUSH * (1 - t)))
        ctx.globalAlpha = t
        ctx.drawImage(b.img, b.x, b.y, b.w, b.h)
        ctx.globalAlpha = 1
        if (t > 0.5) { shown = b; shownFrame = over }
      }

      // Boxes on the frame that is most of the picture.
      const pl = plate.current
      if (pl) {
        Object.assign(pl.style, { left: `${shown.x}px`, top: `${shown.y}px`,
          width: `${shown.w}px`, height: `${shown.h}px` })
      }
      const used = seen(w, physics, forced.current ?? undefined).filter((o) => o.used)
      const { boxes: real, unmatched } = photoBoxes(shownFrame.id, shownFrame.objects ?? [],
        shown.w, shown.h, used, (s) => s - shownFrame.s, hfov)
      drawBoxes(boxes.current, real)
      drawBoxes(markers.current, simMarkers(map, carS, bearing, W, H, unmatched, shown.fpx, H * HORIZON))

      const p = `${Math.round(((shownFrame.t) / 1000))} s of ${Math.round(drive.seconds)} s`
      if (p !== lastProgress) { lastProgress = p; setProgress(p) }
    }
    raf = requestAnimationFrame(draw)
    return () => { alive = false; cancelAnimationFrame(raf) }
  }, [world, map, drive, forced, tick, physics])

  return (
    <div className="city-wrap">
      <div ref={host} className="city-map photos drive" role="img"
        aria-label={`A real dashcam drive along ${map.name}, from the car's front camera`}>
        <canvas ref={canvas} />
        <div className="drive-shade" />
        <div className="drive-bonnet" />
        <div ref={plate} className="plate drive-plate">
          <div ref={boxes} className="boxes perception real" />
        </div>
      </div>
      <div ref={markers} className="perception sim-markers" aria-hidden="true" />
      <p className="street-credit">© Mapillary contributors, CC BY-SA 4.0 · dashcam drive
        {drive.by ? ` by ${drive.by}` : ''}, {drive.date}{progress && ` · ${progress}`}
        {' '}· boxes: Mapillary detections; tags: the simulation's reading</p>
    </div>
  )
}
