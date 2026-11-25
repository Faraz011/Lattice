// The car's camera as real street photos from Mapillary (CC BY-SA 4.0), most of them from
// dashcams. lattice.lens.mapillary chose, for every 5 m of the route, the photo facing the car's
// way (and one facing back, for the rear camera); this plays them as the car drives: the photo
// eases forward as the car approaches the next, which then fades in. The simulation's traffic
// lights, pedestrians and cars are drawn as labelled markers; the people and cars in the photos
// are real and take no part. Photo credits stay on screen.
import { useEffect, useRef, useState, type RefObject } from 'react'

import { between, type Colour, type Physics, type RouteMap, type World } from './driving'
import { offset, poseAt } from './geo'
import { drawBoxes, seen, type Box } from './perception'

export const MAPILLARY_TOKEN = (import.meta.env.VITE_MAPILLARY_TOKEN as string | undefined) ?? ''
const HFOV = 72 // degrees across a typical dashcam frame
const CAMERA_HEIGHT = 1.5
const LANE = -1.9
const AHEAD = 10 // photos whose images are loaded ahead of the car

export interface Photo { s: number; id: string; lng: number; lat: number; angle: number; seq: string; by: string; date: string }
export interface PhotoTrack { source: string; front: Photo[]; rear: Photo[]; coverage: { front: number; rear: number } }

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

export function MapillaryCam({ world, map, track, forced, tick, physics, rear, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const imgA = useRef<HTMLImageElement>(null)
  const imgB = useRef<HTMLImageElement>(null)
  const boxes = useRef<HTMLDivElement>(null)
  const [credit, setCredit] = useState('')
  const back = useRef(rear)
  back.current = rear
  const failed = useRef(onFail)
  failed.current = onFail

  useEffect(() => {
    const urls = new Map<string, string>() // photo id to image address
    const ready = new Set<string>() // images decoded and ready to show
    const asked = new Set<string>()
    let alive = true
    let raf = 0
    let lastCredit = ''
    let errors = 0
    const L = map.length_m

    // Where the car is among the photos: the one just passed, and the next.
    const around = (list: Photo[], s: number) => {
      let i = -1
      for (let k = 0; k < list.length; k++) if (list[k].s <= s) i = k
      const here = list[i] ?? list[list.length - 1]
      const next = list[(i + 1) % list.length]
      return { here, next, index: Math.max(0, i) }
    }

    // Image addresses come from Mapillary's API in batches, a few photos ahead of the car.
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

    const show = (el: HTMLImageElement | null, p: Photo | undefined, opacity: number, scale: number) => {
      if (!el) return
      const u = p && ready.has(p.id) ? urls.get(p.id) : undefined
      if (u && el.dataset.id !== p!.id) { el.src = u; el.dataset.id = p!.id }
      el.style.opacity = u ? String(opacity) : '0'
      el.style.transform = `scale(${scale})`
    }

    const frame = () => {
      raf = requestAnimationFrame(frame)
      const w = world.current
      const el = host.current
      if (!w || !el || !alive) return
      const now = performance.now()
      const alpha = Math.min(1, (now - (w.tickAt ?? now)) / (tick * 1000))
      const carS = between(w.car.prev, w.car.at, alpha, w.length)
      const list = back.current ? track.rear : track.front
      if (!list.length) return
      const { here, next, index } = around(list, carS)
      void prefetch(list, index)
      let gap = next.s - here.s
      if (gap <= 0) gap += L
      let into = carS - here.s
      if (into < 0) into += L
      const t = gap < 40 ? Math.min(1, into / gap) : 0
      // Ease forward into this photo; fade the next in over the last third.
      const fade = t > 0.62 && ready.has(next.id) ? (t - 0.62) / 0.38 : 0
      show(imgA.current, here, 1, 1 + 0.16 * t)
      show(imgB.current, next, fade, 1 + 0.02 * fade)
      const c = here.by ? `photo ${here.by}, ${here.date}` : here.date
      if (c !== lastCredit) { lastCredit = c; setCredit(c) }

      // The simulation's objects, as markers, seen from the photo's direction.
      const W = el.clientWidth
      const H = el.clientHeight
      const f = (W / 2) / Math.tan((HFOV / 2) * (Math.PI / 180))
      const horizon = H * 0.48
      const me = poseAt(map, carS, 6)
      const [cLng, cLat] = offset(me, 0, LANE)
      const view = here.angle
      const found: Box[] = []
      for (const o of seen(w, physics, forced.current ?? undefined)) {
        const p = poseAt(map, o.s, 6)
        const [lng, lat] = offset(p, 0, o.right)
        const east = (lng - cLng) * 111_320 * Math.cos((cLat * Math.PI) / 180)
        const north = (lat - cLat) * 110_540
        const rel = ((Math.atan2(east, north) * 180) / Math.PI - view + 540) % 360 - 180
        const dist = Math.hypot(east, north)
        if (dist < 3 || Math.abs(rel) > HFOV / 2 + 8) continue
        const forward = dist * Math.cos((rel * Math.PI) / 180)
        found.push({ key: o.key, kind: o.kind, x: W / 2 + f * Math.tan((rel * Math.PI) / 180),
          y: horizon + (f * (CAMERA_HEIGHT - o.base)) / forward, w: (f * o.width) / forward,
          h: (f * o.height) / forward, label: o.label, used: o.used })
      }
      drawBoxes(boxes.current, found)
    }
    raf = requestAnimationFrame(frame)
    return () => { alive = false; cancelAnimationFrame(raf) }
  }, [world, map, track, forced, tick, physics])

  return (
    <div className="city-wrap">
      <div ref={host} className="city-map photos" role="img"
        aria-label={`Street photos from the car's ${rear ? 'rear' : 'front'} camera, ${map.name}`}>
        <img ref={imgA} alt="" />
        <img ref={imgB} alt="" />
      </div>
      <div ref={boxes} className="perception sim-markers" aria-hidden="true" />
      <p className="street-credit">© Mapillary contributors, CC BY-SA 4.0{credit && ` · ${credit}`}
        {' '}· markers: simulated objects</p>
    </div>
  )
}
