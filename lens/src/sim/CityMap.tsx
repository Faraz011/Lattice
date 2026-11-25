// The car's world on a real 3D map of London (MapLibre, OpenFreeMap tiles, OpenStreetMap data):
// a chase camera behind the car, extruded buildings, traffic lights at the real junctions,
// zebra crossings at the real crossings, people on them. Everything drawn comes from the
// simulation's state; the map only shows it. Traffic keeps left, as in the UK.
import maplibregl, { type GeoJSONSource, type Map as MapLibre } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, type RefObject } from 'react'

import { colourAt, rel, ROAD_WIDTH, type Colour, type RouteMap, type World } from './driving'
import { box, collection, feature, offset, poseAt, type LngLat } from './geo'

const STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const LANE = -1.9 // the car's lane: left of the road's centre line
const KERB = -6.5 // where the traffic lights stand
const LIGHT: Record<Colour, string> = { red: '#ff2d3f', yellow: '#ffc21a', green: '#22d36b' }
const DRAW_AHEAD = 260 // metres of street furniture drawn ahead of the car
const DRAW_BEHIND = 40

interface Props {
  world: RefObject<World>
  map: RouteMap
  forced: RefObject<Map<number, Colour>>
}

export function CityMap({ world, map, forced }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const night = useRef(false)

  useEffect(() => {
    if (!container.current) return
    const start = poseAt(map, 0, 30)
    const m = new maplibregl.Map({
      container: container.current, style: STYLE, center: [start.lng, start.lat], zoom: 19.2,
      pitch: 60, bearing: start.bearing, interactive: false,
      // Keep the last frame readable, so screenshots and screen recordings of the demo work.
      canvasContextAttributes: { preserveDrawingBuffer: true },
      attributionControl: { compact: true },
    })
    let raf = 0
    let ready = false
    let camera = { bearing: start.bearing }
    let last = performance.now()

    m.on('load', () => {
      addLayers(m, map)
      ready = true
    })

    const frame = () => {
      const w = world.current
      if (w && ready) {
        // Chase camera: behind the car, looking down the road, turning smoothly. The easing is
        // by elapsed time, so the camera keeps up however fast the screen redraws.
        const now = performance.now()
        const ease = 1 - Math.exp(-Math.min(now - last, 500) / 450)
        last = now
        const look = poseAt(map, w.car.at, 30)
        const turn = ((look.bearing - camera.bearing + 540) % 360) - 180
        camera = { bearing: (camera.bearing + turn * ease + 360) % 360 }
        const centre = offset({ ...poseAt(map, w.car.at), bearing: camera.bearing }, 22, LANE)
        m.jumpTo({ center: centre, bearing: camera.bearing })
        draw(m, map, w, forced.current ?? undefined)
        if (night.current !== w.night) {
          night.current = w.night
          container.current?.classList.toggle('night', w.night)
        }
        container.current?.classList.toggle('rain', w.rain)
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      m.remove()
    }
  }, [map, world, forced])

  return <div ref={container} className="city-map" role="img"
    aria-label={`A 3D map of ${map.name}, following the car`} />
}

function addLayers(m: MapLibre, map: RouteMap) {
  const empty = collection([])
  m.addSource('route', { type: 'geojson', data: { type: 'Feature', properties: {},
    geometry: { type: 'LineString', coordinates: map.route } } })
  for (const id of ['sensor', 'crossings', 'peds', 'poles', 'heads', 'cars', 'brake']) {
    m.addSource(id, { type: 'geojson', data: empty })
  }
  const before = m.getLayer('building-3d') ? 'building-3d' : undefined
  m.addLayer({ id: 'route', type: 'line', source: 'route',
    paint: { 'line-color': '#5b8def', 'line-width': 3, 'line-opacity': 0.35 } }, before)
  m.addLayer({ id: 'sensor', type: 'fill', source: 'sensor',
    paint: { 'fill-color': '#2f6fed', 'fill-opacity': 0.12 } }, before)
  m.addLayer({ id: 'crossings', type: 'fill', source: 'crossings',
    paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.85 } }, before)
  const solid = (id: string, color: unknown, base: unknown, height: unknown) => m.addLayer({
    id, type: 'fill-extrusion', source: id,
    paint: { 'fill-extrusion-color': color as string, 'fill-extrusion-base': base as number,
      'fill-extrusion-height': height as number, 'fill-extrusion-opacity': 1 },
  } as maplibregl.FillExtrusionLayerSpecification)
  solid('poles', '#2b2f38', 0, 4.2)
  solid('heads', ['get', 'color'], 4.2, 5.6)
  solid('peds', '#f2b134', 0, 1.8)
  solid('cars', ['get', 'color'], 0.25, 1.55)
  solid('brake', '#ff2d3f', 0.7, 1.1)
}

function draw(m: MapLibre, map: RouteMap, w: World, forced?: Map<number, Colour>) {
  const near = (at: number) => { const d = rel(w, at); return d > -DRAW_BEHIND && d < DRAW_AHEAD }
  const set = (id: string, data: ReturnType<typeof collection>) =>
    (m.getSource(id) as GeoJSONSource | undefined)?.setData(data)

  const crossings = w.crosswalks.filter(near).flatMap((at) => {
    const p = poseAt(map, at, 6)
    // Zebra stripes: bars along the direction of travel, side by side across the road.
    return Array.from({ length: 7 }, (_, k) => feature(box(p, 3, 0.8, -6 + k * 2)))
  })
  set('crossings', collection(crossings))

  const lights = w.lights.filter((l) => near(l.at))
  set('poles', collection(lights.map((l) => feature(box(poseAt(map, l.at, 6), 0.45, 0.45, KERB)))))
  set('heads', collection(lights.map((l) => feature(box(poseAt(map, l.at, 6), 0.9, 0.9, KERB),
    { color: LIGHT[colourAt(l, w.time, forced)] }))))

  set('peds', collection(w.pedestrians.filter((x) => near(x.crosswalk)).map((x) => {
    const across = x.wait > 0 ? -7.5 : -6 + (x.x / ROAD_WIDTH) * 12
    return feature(box(poseAt(map, x.crosswalk, 6), 0.7, 0.7, across))
  })))

  const car = poseAt(map, w.car.at, 6)
  // What the car can see: 120 m of road ahead, drawn as a fan following the route.
  const left: LngLat[] = []
  const right: LngLat[] = []
  for (let d = 2; d <= 120; d += 8) {
    const p = poseAt(map, w.car.at + d, 6)
    const half = 1.2 + d * 0.06
    left.push(offset(p, 0, LANE - half))
    right.push(offset(p, 0, LANE + half))
  }
  set('sensor', collection([feature([...left, ...right.reverse(), left[0]])]))
  const cars = [feature(box(car, 4.6, 1.9, LANE), { color: '#2f6fed' })]
  if (w.lead && near(w.lead.at)) {
    cars.push(feature(box(poseAt(map, w.lead.at, 6), 4.6, 1.9, LANE), { color: '#7d8799' }))
  }
  set('cars', collection(cars))
  const braking = w.action === 2
  set('brake', collection(braking ? [-0.6, 0.6].map((r) =>
    feature(box(car, 0.3, 0.5, LANE + r, -2.35))) : []))
}

export type { LngLat }
