// The car's world on Google's Photorealistic 3D Tiles of London, through CesiumJS and a Cesium ion
// token (VITE_CESIUM_ION_TOKEN). Buildings, trees, road markings and crossings are Google's
// photogrammetry; the cars, traffic lights and pedestrians are the simulation's, set on the real
// ground height sampled from the 3D tiles. Positions are drawn between simulation ticks so
// everything moves smoothly. Google's terms require their credits on screen: Cesium shows them.
import { useEffect, useRef, type RefObject } from 'react'
import type * as CesiumNS from 'cesium'

import {
  colourAt, rel, ROAD_WIDTH, type Colour, type Physics, type RouteMap, type World,
} from './driving'
import { offset, poseAt, type Pose } from './geo'
import { drawBoxes, seen as detect, type Box as Detection } from './perception'

type Ground = Pose & { ground: number } // a pose with the ground's height there

declare global {
  interface Window { Cesium?: typeof CesiumNS; CESIUM_BASE_URL?: string }
}

const VERSION = '1.147.0'
const BASE = `https://cdn.jsdelivr.net/npm/cesium@${VERSION}/Build/Cesium/`
export const ION_TOKEN = (import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined) ?? ''
// Local development only: `?photo` tries the view with the evaluation token built into CesiumJS,
// for checking the view before a token is set up. Never in a production build.
export const TRY_PHOTO = import.meta.env.DEV && new URLSearchParams(window.location.search).has('photo')
// `?open` forces the open map, token or not: for a machine whose graphics cannot run the
// photorealistic city.
export const FORCE_OPEN = new URLSearchParams(window.location.search).has('open')
const LANE = -1.9 // keep left
const KERB = -6.5
const STEP = 20 // metres between sampled ground heights
const FALLBACK_HEIGHT = 60 // metres above the ellipsoid in central London, until sampled
const LAMP: Record<Colour, string> = { red: '#ff2d3f', yellow: '#ffc21a', green: '#22d36b' }

let loading: Promise<typeof CesiumNS> | null = null

// CesiumJS from its CDN, once per page: 6 MB, so only fetched when the photoreal view is used.
export function loadCesium(): Promise<typeof CesiumNS> {
  if (window.Cesium) return Promise.resolve(window.Cesium)
  loading ??= new Promise((resolve, reject) => {
    window.CESIUM_BASE_URL = BASE
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = `${BASE}Widgets/widgets.css`
    document.head.append(css)
    const js = document.createElement('script')
    js.src = `${BASE}Cesium.js`
    js.onload = () => (window.Cesium ? resolve(window.Cesium) : reject(new Error('Cesium did not load')))
    js.onerror = () => reject(new Error('Could not load CesiumJS from its CDN'))
    document.head.append(js)
  })
  return loading
}

interface Props {
  world: RefObject<World>
  map: RouteMap
  forced: RefObject<Map<number, Colour>>
  tick: number // seconds per simulation step, for drawing between steps
  physics: Physics
  camera: Camera
  onFail: (why: string) => void
}

// Which of the car's cameras the view shows: the front camera at windscreen height (what the
// car's network sees), the rear camera, or a chase view from behind and above.
export type Camera = 'front' | 'rear' | 'chase'

export function PhotoCity({ world, map, forced, tick, physics, camera, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const boxes = useRef<HTMLDivElement>(null)
  const cam = useRef(camera)
  cam.current = camera
  const failed = useRef(onFail)
  failed.current = onFail

  useEffect(() => {
    let alive = true
    let cleanup = () => {}
    loadCesium().then(async (C) => {
      if (!alive || !host.current) return
      if (ION_TOKEN) C.Ion.defaultAccessToken = ION_TOKEN
      const viewer = new C.Viewer(host.current, {
        animation: false, timeline: false, baseLayerPicker: false, geocoder: false,
        homeButton: false, sceneModePicker: false, navigationHelpButton: false,
        fullscreenButton: false, infoBox: false, selectionIndicator: false,
        baseLayer: false, requestRenderMode: false,
        contextOptions: { webgl: { preserveDrawingBuffer: true } },
      })
      viewer.scene.globe.show = false // Google's tiles carry their own ground
      if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = true
      try {
        // Lighter than Cesium's defaults, for laptops with modest GPUs: slightly coarser detail
        // in the distance, and a cap on how much of the city stays in memory.
        const tiles = await C.createGooglePhotorealistic3DTileset({ onlyUsingWithGoogleGeocoder: true },
          { maximumScreenSpaceError: 24, cacheBytes: 384 * 1024 * 1024,
            maximumCacheOverflowBytes: 128 * 1024 * 1024, foveatedScreenSpaceError: true,
            dynamicScreenSpaceError: true })
        viewer.scene.primitives.add(tiles)
        viewer.resolutionScale = Math.min(1, 1.25 / window.devicePixelRatio)
      } catch (e) {
        failed.current(`Could not load Google's 3D tiles: ${(e as Error).message}`)
        viewer.destroy()
        return
      }
      cleanup = drive(C, viewer, { world, map, forced, tick, physics, cam, boxes: boxes.current,
        host: host.current })
    }).catch((e: Error) => failed.current(e.message))
    return () => { alive = false; cleanup() }
  }, [world, map, forced, tick, physics])

  return (
    <div className="city-wrap">
      <div ref={host} className="city-map photo loading" role="img"
        aria-label={`Photorealistic 3D London, from the car's ${camera} camera: ${map.name}`} />
      <div ref={boxes} className="perception" aria-hidden="true" />
      <p className="loading-note">Loading London in 3D</p>
    </div>
  )
}

interface Drive {
  world: RefObject<World>
  map: RouteMap
  forced: RefObject<Map<number, Colour>>
  tick: number
  physics: Physics
  cam: RefObject<Camera>
  boxes: HTMLDivElement | null
  host: HTMLDivElement
}

function drive(C: typeof CesiumNS, viewer: CesiumNS.Viewer, d: Drive): () => void {
  const { world, map, forced, tick, physics, cam, boxes, host } = d
  const scene = viewer.scene
  const frustum = viewer.camera.frustum as CesiumNS.PerspectiveFrustum
  frustum.fov = C.Math.toRadians(72) // a wide-angle car camera
  frustum.near = 0.2
  const L = map.length_m

  // Ground height along the route, sampled from the 3D tiles a stretch ahead at a time.
  const heights = new Float64Array(Math.ceil(L / STEP) + 1).fill(NaN)
  let pending = false
  // The road's height at sample k. Google's 3D city includes trees, buses and parked cars, so a
  // sample can land on a roof: the lowest of a sample and its neighbours is the road. Where
  // nothing is sampled yet, the nearest sample stands in.
  let known = FALLBACK_HEIGHT
  const road = (k: number): number => {
    const n = heights.length
    let low = NaN
    for (const j of [k - 1, k, k + 1]) {
      const h = heights[((j % n) + n) % n]
      if (!Number.isNaN(h) && !(h > low)) low = h
    }
    if (!Number.isNaN(low)) return low
    for (let r = 2; r < 25; r++) {
      for (const j of [k - r, k + r]) {
        const h = heights[((j % n) + n) % n]
        if (!Number.isNaN(h)) return h
      }
    }
    return known
  }
  const groundAt = (s: number) => {
    const at = ((s % L) + L) % L
    const k = Math.floor(at / STEP)
    const a = road(k)
    const b = road(k + 1)
    return a + (b - a) * ((at - k * STEP) / STEP)
  }
  const sampleAhead = () => {
    const w = world.current
    if (pending || !w) return
    const todo: number[] = []
    for (let d = -40; d <= 240; d += STEP) {
      const k = Math.floor((((w.car.at + d) % L) + L) % L / STEP)
      if (Number.isNaN(heights[k]) && !todo.includes(k)) todo.push(k)
    }
    if (!todo.length) return
    pending = true
    const points = todo.map((k) => {
      const p = poseAt(map, k * STEP)
      return C.Cartographic.fromDegrees(p.lng, p.lat)
    })
    // Our own cars, poles and people are not the ground: sampling must look through them.
    scene.sampleHeightMostDetailed(points, viewer.entities.values).then((done) => {
      done.forEach((c, i) => {
        if (c && Number.isFinite(c.height)) { heights[todo[i]] = c.height; known = c.height }
      })
      host.classList.remove('loading')
    }).catch(() => {}).finally(() => { pending = false })
  }
  const sampler = window.setInterval(sampleAhead, 1500)

  const at = (pose: Pose, forward: number, right: number, up: number) => {
    const [lng, lat] = offset(pose, forward, right)
    return C.Cartesian3.fromDegrees(lng, lat, up)
  }
  const orient = (position: CesiumNS.Cartesian3, bearing: number) =>
    C.Transforms.headingPitchRollQuaternion(position,
      new C.HeadingPitchRoll(C.Math.toRadians(bearing - 90), 0, 0))
  const col = (hex: string) => C.Color.fromCssColorString(hex)

  // A car: a body and a glasshouse, two boxes that move and turn together.
  type Box = { body: CesiumNS.Entity; cabin: CesiumNS.Entity }
  const makeCar = (color: string, length: number): Box => ({
    body: viewer.entities.add({ box: { dimensions: new C.Cartesian3(length, 1.85, 0.85),
      material: col(color) } }),
    cabin: viewer.entities.add({ box: { dimensions: new C.Cartesian3(length * 0.55, 1.6, 0.6),
      material: col('#1b2230').withAlpha(0.92) } }),
  })
  const placeCar = (b: Box, pose: Ground, right: number, show: boolean, back = 0) => {
    b.body.show = show
    b.cabin.show = show
    if (!show) return
    const ground = pose.ground
    const p1 = at(pose, -back, right, ground + 0.75)
    const p2 = at(pose, -back - 0.3, right, ground + 1.45)
    b.body.position = new C.ConstantPositionProperty(p1)
    b.cabin.position = new C.ConstantPositionProperty(p2)
    b.body.orientation = new C.ConstantProperty(orient(p1, pose.bearing))
    b.cabin.orientation = new C.ConstantProperty(orient(p2, pose.bearing))
  }

  const ego = makeCar('#2f6fed', 4.6)
  const brake = [0, 1].map(() => viewer.entities.add({ box: {
    dimensions: new C.Cartesian3(0.12, 0.45, 0.2), material: col('#ff2d3f') } }))
  const others = new Map<number, Box>()
  const crossers = new Map<number, Box>()
  const people = new Map<number, CesiumNS.Entity>()
  const lights = map.signals.map(() => ({
    pole: viewer.entities.add({ cylinder: { length: 4.2, topRadius: 0.09, bottomRadius: 0.09,
      material: col('#2b2f38') } }),
    lamp: viewer.entities.add({ box: { dimensions: new C.Cartesian3(0.45, 0.45, 1.2),
      material: col('#22d36b') } }),
  }))

  let bearing = poseAt(map, world.current?.car.at ?? 0, 30).bearing
  let last = performance.now()
  const smooth = (prev: number, now: number, alpha: number) => {
    let d = now - prev
    if (d > L / 2) d -= L
    if (d < -L / 2) d += L
    return prev + d * alpha
  }

  const frame = () => {
    const w = world.current
    if (!w) return
    const now = performance.now()
    const alpha = Math.min(1, (now - (w.tickAt ?? now)) / (tick * 1000))
    const poseOf = (s: number, span = 6): Ground => ({ ...poseAt(map, s, span), ground: groundAt(s) })

    // Our car, drawn between its last two positions.
    const carS = smooth(w.car.prev, w.car.at, alpha)
    const car = poseOf(carS)
    const mode = cam.current ?? 'front'
    placeCar(ego, car, LANE, mode === 'chase') // from its own cameras, the car is not in view
    brake.forEach((e, k) => {
      e.show = w.action === 2 && mode === 'chase'
      const p = at(car, -2.32, LANE + (k ? 0.6 : -0.6), car.ground + 0.95)
      e.position = new C.ConstantPositionProperty(p)
      e.orientation = new C.ConstantProperty(orient(p, car.bearing))
    })

    // Traffic.
    const seen = new Set<number>()
    for (const v of w.traffic) {
      const d = rel(w, v.at)
      const show = d > -60 && d < 330
      let box = others.get(v.id)
      if (!box) { box = makeCar(v.color, v.length); others.set(v.id, box) }
      seen.add(v.id)
      const s = smooth(v.prev, v.at, alpha)
      const p = poseOf(s)
      const facing = v.lane === 1 ? p : { ...p, bearing: (p.bearing + 180) % 360 }
      placeCar(box, facing, LANE, show) // keep left, in whichever direction it drives
    }
    for (const [id, box] of others) {
      if (!seen.has(id)) { viewer.entities.remove(box.body); viewer.entities.remove(box.cabin); others.delete(id) }
    }

    // Cross traffic at the junction ahead.
    const crossing = new Set<number>()
    for (const c of w.cross) {
      let box = crossers.get(c.id)
      if (!box) { box = makeCar(c.color, 4.5); crossers.set(c.id, box) }
      crossing.add(c.id)
      const j = poseOf(c.junction + 8, 10)
      const x = c.prevX + (c.x - c.prevX) * alpha
      const side = { ...j, bearing: (j.bearing + (c.dir === 1 ? 90 : 270)) % 360 }
      const [lng, lat] = offset(j, 0, x)
      placeCar(box, { ...side, lng, lat }, c.dir === 1 ? -1.9 : 1.9, true)
    }
    for (const [id, box] of crossers) {
      if (!crossing.has(id)) { viewer.entities.remove(box.body); viewer.entities.remove(box.cabin); crossers.delete(id) }
    }

    // Traffic lights at the real junctions, lit with their current colour.
    w.lights.forEach((l, k) => {
      const e = lights[k]
      if (!e) return
      const d = rel(w, l.at)
      const show = d > -30 && d < 280
      e.pole.show = show
      e.lamp.show = show
      if (!show) return
      const p = poseOf(l.at)
      e.pole.position = new C.ConstantPositionProperty(at(p, 0, KERB, p.ground + 2.1))
      e.lamp.position = new C.ConstantPositionProperty(at(p, 0, KERB, p.ground + 4.6))
      e.lamp.box!.material = new C.ColorMaterialProperty(
        col(LAMP[colourAt(l, w.time, forced.current ?? undefined)]))
    })

    // People on the crossings.
    const here = new Set<number>()
    for (const ped of w.pedestrians) {
      let e = people.get(ped.id)
      if (!e) {
        e = viewer.entities.add({ cylinder: { length: 1.75, topRadius: 0.24, bottomRadius: 0.2,
          material: col('#f2b134') } })
        people.set(ped.id, e)
      }
      here.add(ped.id)
      const p = poseOf(ped.crosswalk)
      const across = ped.wait > 0 ? -7.5 : -6 + (ped.x / ROAD_WIDTH) * 12
      e.position = new C.ConstantPositionProperty(at(p, 0, across, p.ground + 0.9))
    }
    for (const [id, e] of people) if (!here.has(id)) { viewer.entities.remove(e); people.delete(id) }

    // The camera, turning smoothly by elapsed time. The front and rear cameras sit on the car at
    // windscreen height and look along the road; the chase view sits behind and above.
    const look = poseAt(map, carS, mode === 'chase' ? 30 : 14)
    const turn = ((look.bearing - bearing + 540) % 360) - 180
    const settle = mode === 'chase' ? 450 : 220
    bearing = (bearing + turn * (1 - Math.exp(-Math.min(now - last, 500) / settle)) + 360) % 360
    last = now
    const heading = { ...car, bearing }
    if (mode === 'front') {
      viewer.camera.setView({ destination: at(heading, 0.9, LANE, car.ground + 1.4), orientation: {
        heading: C.Math.toRadians(bearing), pitch: C.Math.toRadians(-3), roll: 0 } })
    } else if (mode === 'rear') {
      viewer.camera.setView({ destination: at(heading, -2.4, LANE, car.ground + 1.3), orientation: {
        heading: C.Math.toRadians((bearing + 180) % 360), pitch: C.Math.toRadians(-4), roll: 0 } })
    } else {
      viewer.camera.setView({ destination: at(heading, -26, LANE, car.ground + 13), orientation: {
        heading: C.Math.toRadians(bearing), pitch: C.Math.toRadians(-22), roll: 0 } })
    }

    // What the cameras detect, boxed on the view.
    const found: Detection[] = []
    const camPos = viewer.camera.positionWC
    const dir = viewer.camera.directionWC
    const toward = new C.Cartesian3()
    for (const o of detect(w, physics, forced.current ?? undefined)) {
      const p = poseOf(o.s)
      const bottom = at(p, 0, o.right, p.ground + o.base)
      const top = at(p, 0, o.right, p.ground + o.base + o.height)
      C.Cartesian3.subtract(bottom, camPos, toward)
      if (C.Cartesian3.dot(toward, dir) <= 1) continue // behind the camera
      const b = C.SceneTransforms.worldToWindowCoordinates(scene, bottom)
      const t = C.SceneTransforms.worldToWindowCoordinates(scene, top)
      if (!b || !t) continue
      const h = Math.abs(b.y - t.y)
      found.push({ key: o.key, kind: o.kind, x: b.x, y: b.y, w: h * (o.width / o.height),
        h, label: o.label, used: o.used })
    }
    drawBoxes(boxes, mode === 'chase' ? [] : found)

    host.classList.toggle('night', w.night)
    host.classList.toggle('rain', w.rain)
  }
  const remove = scene.preRender.addEventListener(frame)
  return () => {
    remove()
    window.clearInterval(sampler)
    if (!viewer.isDestroyed()) viewer.destroy()
  }
}
