// The car's camera as real street photos from Mapillary (CC BY-SA 4.0), most from dashcams.
// lattice.lens.mapillary chose, for every 5 m of the route, a daylight photo facing the car's
// way and one facing back, preferring one continuous drive; at night the same photos are shown
// darkened, as there are too few night photos to drive on.
//
// Each photo is a frame: the image, and boxes around the real vehicles, people and traffic
// lights Mapillary detected in it. The frame turns to match the car's heading, pushes in as the
// car drives past where the photo was taken, and fades into the next. The boxes the network's
// inputs correspond to (the car ahead, the next light, someone crossing) carry the simulation's
// reading of them; where the photo has no such object, a small 'sim' marker stands in.
import { useEffect, useRef, useState, type RefObject } from 'react'

import { between, type Colour, type Physics, type RouteMap, type World } from './driving'
import { offset, poseAt } from './geo'
import { drawBoxes, seen, type Box, type Kind, type Seen } from './perception'

export const MAPILLARY_TOKEN = (import.meta.env.VITE_MAPILLARY_TOKEN as string | undefined) ?? ''
const HFOV = 72 // degrees across a typical dashcam frame
const CAMERA_HEIGHT = 1.5
const LANE = -1.9
const AHEAD = 10 // photos whose images are loaded ahead of the car
const FADE_MS = 650

interface Detected { kind: string; box: [number, number, number, number] }
export interface Photo {
  s: number; id: string; lng: number; lat: number; angle: number; seq: string; by: string
  date: string; objects?: Detected[]
}
export interface PhotoTrack {
  source: string; front: Photo[]; rear: Photo[]; front_night?: Photo[]; rear_night?: Photo[]
  coverage: Record<string, number>
}

export async function loadPhotoTrack(): Promise<PhotoTrack | null> {
  if (!MAPILLARY_TOKEN) return null
  const r = await fetch(`${import.meta.env.BASE_URL}maps/london-mapillary.json`)
  return r.ok ? r.json() : null
}

interface Props {
  world: RefObject<World>
  map: RouteMap
  track: PhotoTrack
  forced: RefObject<Map<number, Colour>>
  tick: number
  physics: Physics
  rear: boolean
  onFail: (why: string) => void
}

interface Frame { el: HTMLDivElement; img: HTMLImageElement; plate: HTMLDivElement; boxes: HTMLDivElement }

const VEHICLES = new Set(['car', 'bus', 'truck', 'vehicle', 'motorcycle'])
const LABELS: Record<string, string> = { car: 'car', bus: 'bus', truck: 'truck', vehicle: 'vehicle',
  motorcycle: 'motorbike', person: 'person', cyclist: 'cyclist', rider: 'rider', light: 'traffic light' }

export function MapillaryCam({ world, map, track, forced, tick, physics, rear, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const frameA = useRef<HTMLDivElement>(null)
  const frameB = useRef<HTMLDivElement>(null)
  const markers = useRef<HTMLDivElement>(null)
  const [credit, setCredit] = useState('')
  const back = useRef(rear)
  back.current = rear
  const failed = useRef(onFail)
  failed.current = onFail

  useEffect(() => {
    const urls = new Map<string, string>()
    const ready = new Set<string>()
    const asked = new Set<string>()
    let alive = true
    let raf = 0
    let lastCredit = ''
    let errors = 0
    let shown: Photo | null = null
    let under: Photo | null = null
    let switchedAt = 0
    let lastList: Photo[] | null = null
    const L = map.length_m
    const frame = (el: HTMLDivElement | null): Frame | null => el && {
      el, img: el.querySelector('img')!, plate: el.querySelector('.plate') as HTMLDivElement,
      boxes: el.querySelector('.boxes') as HTMLDivElement,
    }

    const around = (list: Photo[], s: number) => {
      let i = -1
      for (let k = 0; k < list.length; k++) if (list[k].s <= s) i = k
      return { here: list[i] ?? list[list.length - 1], next: list[(i + 1) % list.length],
        index: Math.max(0, i) }
    }

    const prefetch = async (list: Photo[], from: number) => {
      const want = Array.from({ length: AHEAD }, (_, k) => list[(from + k) % list.length])
        .filter((p) => p && !asked.has(p.id))
      if (!want.length) return
      want.forEach((p) => asked.add(p.id))
      try {
        const r = await fetch(`https://graph.mapillary.com/?ids=${want.map((p) => p.id).join(',')}` +
          `&fields=thumb_2048_url&access_token=${encodeURIComponent(MAPILLARY_TOKEN)}`)
        if (!r.ok) throw new Error(`Mapillary ${r.status}: ${(await r.text()).slice(0, 160)}`)
        const got = await r.json() as Record<string, { thumb_2048_url?: string }>
        for (const p of want) {
          const u = got[p.id]?.thumb_2048_url
          if (!u) continue
          urls.set(p.id, u)
          const img = new Image()
          img.onload = () => ready.add(p.id)
          img.src = u
        }
        errors = 0
      } catch (e) {
        want.forEach((p) => asked.delete(p.id))
        if (++errors >= 3 && !ready.size) failed.current((e as Error).message)
      }
    }

    // Size a frame's plate to cover the view the way the photo does, so boxes given as
    // fractions of the image land on the objects.
    const fit = (f: Frame, W: number, H: number) => {
      const iw = f.img.naturalWidth || 4
      const ih = f.img.naturalHeight || 3
      const k = Math.max(W / iw, H / ih)
      const pw = iw * k
      const ph = ih * k
      Object.assign(f.plate.style, { width: `${pw}px`, height: `${ph}px`,
        left: `${(W - pw) / 2}px`, top: `${(H - ph) / 2}px` })
      return { pw, ph }
    }

    // Boxes around the photo's real objects; the ones the network's inputs stand for carry
    // the simulation's reading. Returns the network's objects the photo had no match for.
    const label = (f: Frame, p: Photo, pw: number, ph: number, used: Seen[]): Seen[] => {
      const objects = p.objects ?? []
      const centre = (b: Detected['box']) => (b[0] + b[2]) / 2
      const area = (b: Detected['box']) => (b[2] - b[0]) * (b[3] - b[1])
      const taken = new Map<number, Seen>()
      const unmatched: Seen[] = []
      for (const u of used) {
        const want = u.kind === 'car' ? (o: Detected) => VEHICLES.has(o.kind) && Math.abs(centre(o.box) - 0.5) < 0.22
          : u.kind === 'pedestrian' ? (o: Detected) => o.kind === 'person' && Math.abs(centre(o.box) - 0.5) < 0.35
          : (o: Detected) => o.kind === 'light'
        let best = -1
        objects.forEach((o, i) => {
          if (!taken.has(i) && want(o) && (best < 0 || area(o.box) > area(objects[best].box))) best = i
        })
        if (best >= 0) taken.set(best, u)
        else unmatched.push(u)
      }
      const boxes: Box[] = objects.map((o, i) => {
        const u = taken.get(i)
        const kind: Kind = u ? u.kind : o.kind === 'light' ? 'green'
          : o.kind === 'person' || o.kind === 'cyclist' || o.kind === 'rider' ? 'pedestrian' : 'car'
        const [x0, y0, x1, y1] = o.box
        return { key: `${p.id}${i}`, kind: o.kind === 'light' && !u ? 'light-real' as Kind : kind,
          x: ((x0 + x1) / 2) * pw, y: y1 * ph, w: (x1 - x0) * pw, h: (y1 - y0) * ph,
          // A light's colour is the simulation's, not the photo's: the tag says so.
          label: u ? (o.kind === 'light' ? `${u.label} (sim)` : u.label) : LABELS[o.kind] ?? o.kind,
          used: Boolean(u) }
      })
      drawBoxes(f.boxes, boxes)
      return unmatched
    }

    const place = (f: Frame | null, p: Photo | null, opacity: number, zoom: number, pan: number,
      W: number, H: number, used: Seen[]): Seen[] => {
      if (!f) return used
      const u = p && ready.has(p.id) ? urls.get(p.id) : undefined
      if (!p || !u) { f.el.style.opacity = '0'; return used }
      if (f.el.dataset.id !== p.id) { f.img.src = u; f.el.dataset.id = p.id }
      f.el.style.opacity = String(opacity)
      f.el.style.transform = `translateX(${pan}px) scale(${zoom})`
      const { pw, ph } = fit(f, W, H)
      return label(f, p, pw, ph, used)
    }

    const draw = () => {
      raf = requestAnimationFrame(draw)
      const w = world.current
      const el = host.current
      if (!w || !el || !alive) return
      const W = el.clientWidth
      const H = el.clientHeight
      const now = performance.now()
      const alpha = Math.min(1, (now - (w.tickAt ?? now)) / (tick * 1000))
      const carS = between(w.car.prev, w.car.at, alpha, w.length)
      const isRear = back.current
      const night = w.night && (isRear ? track.rear_night : track.front_night)?.length
      const list = night ? (isRear ? track.rear_night! : track.front_night!) : isRear ? track.rear : track.front
      if (!list.length) return
      if (list !== lastList) { lastList = list; shown = null; under = null }
      el.classList.toggle('night', w.night && !night)
      el.classList.toggle('rain', w.rain)
      const { here, next, index } = around(list, carS)
      void prefetch(list, index)
      let gap = next.s - here.s
      if (gap <= 0) gap += L
      let into = carS - here.s
      if (into < 0) into += L
      const t = gap < 40 ? Math.min(1, into / gap) : 0

      // Show the nearer photo; switch to the next past halfway, as a timed fade.
      const want = t > 0.5 && ready.has(next.id) ? next : here
      if (!shown || (want.id !== shown.id && ready.has(want.id))) {
        under = shown
        shown = want
        switchedAt = now
      }
      const fade = Math.min(1, (now - switchedAt) / FADE_MS)
      const eased = fade * fade * (3 - 2 * fade)
      // Push in with distance driven past the photo; turn the photo to the car's heading.
      const route = poseAt(map, carS, 12).bearing
      const view = isRear ? (route + 180) % 360 : route
      const f = (W / 2) / Math.tan((HFOV / 2) * (Math.PI / 180))
      const zoomFor = (p: Photo) => {
        let past = carS - p.s
        if (past < -L / 2) past += L
        return Math.max(1.04, Math.min(1.32, 1.1 + 0.011 * past))
      }
      const panFor = (p: Photo) => {
        const diff = ((p.angle - view + 540) % 360) - 180
        return Math.max(-0.14 * W, Math.min(0.14 * W, -f * Math.tan((diff * Math.PI) / 180)))
      }

      const used = seen(w, physics, forced.current ?? undefined).filter((o) => o.used)
      const fa = frame(frameA.current)
      const fb = frame(frameB.current)
      place(fa, under, 1 - eased * 0.15, under ? zoomFor(under) : 1, under ? panFor(under) : 0, W, H, [])
      const unmatched = place(fb, shown, under ? eased : 1, shown ? zoomFor(shown) : 1,
        shown ? panFor(shown) : 0, W, H, used)
      if (fade >= 1) under = null

      const c = `${shown?.by ? `photo ${shown.by}, ` : ''}${shown?.date ?? ''}`
      if (c !== lastCredit) { lastCredit = c; setCredit(c) }

      // The network's objects the photo has no match for: small markers where they would be.
      const horizon = H * 0.48
      const me = poseAt(map, carS, 6)
      const [cLng, cLat] = offset(me, 0, LANE)
      const extra: Box[] = []
      for (const o of unmatched) {
        const p = poseAt(map, o.s, 6)
        const [lng, lat] = offset(p, 0, o.right)
        const east = (lng - cLng) * 111_320 * Math.cos((cLat * Math.PI) / 180)
        const north = (lat - cLat) * 110_540
        const rel = ((Math.atan2(east, north) * 180) / Math.PI - view + 540) % 360 - 180
        const dist = Math.hypot(east, north)
        if (dist < 3 || Math.abs(rel) > HFOV / 2 + 8) continue
        const forward = dist * Math.cos((rel * Math.PI) / 180)
        extra.push({ key: o.key, kind: o.kind, x: W / 2 + f * Math.tan((rel * Math.PI) / 180),
          y: horizon + (f * (CAMERA_HEIGHT - o.base)) / forward, w: (f * o.width) / forward,
          h: (f * o.height) / forward, label: o.label, used: true })
      }
      drawBoxes(markers.current, extra)
    }
    raf = requestAnimationFrame(draw)
    return () => { alive = false; cancelAnimationFrame(raf) }
  }, [world, map, track, forced, tick, physics])

  return (
    <div className="city-wrap">
      <div ref={host} className="city-map photos" role="img"
        aria-label={`Street photos from the car's ${rear ? 'rear' : 'front'} camera, ${map.name}`}>
        {[frameA, frameB].map((ref, k) => (
          <div key={k} ref={ref} className="photo-frame">
            <div className="plate"><img alt="" /><div className="boxes perception real" /></div>
          </div>
        ))}
      </div>
      <div ref={markers} className="perception sim-markers" aria-hidden="true" />
      <p className="street-credit">© Mapillary contributors, CC BY-SA 4.0{credit && ` · ${credit}`}
        {' '}· boxes: Mapillary detections; tags: the simulation's reading</p>
    </div>
  )
}
