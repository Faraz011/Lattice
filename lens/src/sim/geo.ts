// From "metres along the route" to the map: positions, headings and small shapes (a car, a
// crossing) as polygons in longitude and latitude. Flat-earth maths, exact enough over a city.
import type { RouteMap } from './driving'

export type LngLat = [number, number]

const M_PER_DEG_LAT = 110_540
const mPerDegLng = (lat: number) => 111_320 * Math.cos((lat * Math.PI) / 180)

export interface Pose { lng: number; lat: number; bearing: number } // bearing: degrees from north

function bearingOf(a: LngLat, b: LngLat): number {
  const dx = (b[0] - a[0]) * mPerDegLng(a[1])
  const dy = (b[1] - a[1]) * M_PER_DEG_LAT
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360
}

function pointAt(map: RouteMap, s: number): LngLat {
  const L = map.length_m
  const at = ((s % L) + L) % L
  const cum = map.cumulative_m
  let lo = 0
  let hi = cum.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (cum[mid] <= at) lo = mid
    else hi = mid
  }
  const a = map.route[lo]
  const b = map.route[hi]
  const t = (at - cum[lo]) / Math.max(cum[hi] - cum[lo], 1e-6)
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

// Where `s` metres along the route is, heading along it (looked at over `span` metres, so the
// heading turns smoothly through corners).
export function poseAt(map: RouteMap, s: number, span = 4): Pose {
  const [lng, lat] = pointAt(map, s)
  return { lng, lat, bearing: bearingOf(pointAt(map, s - span / 2), pointAt(map, s + span / 2)) }
}

// A point `forward` metres ahead and `right` metres to the right of a pose.
export function offset(p: Pose, forward: number, right: number): LngLat {
  const b = (p.bearing * Math.PI) / 180
  const north = forward * Math.cos(b) - right * Math.sin(b)
  const east = forward * Math.sin(b) + right * Math.cos(b)
  return [p.lng + east / mPerDegLng(p.lat), p.lat + north / M_PER_DEG_LAT]
}

// A rectangle centred `right` metres off a pose: `length` along it, `width` across.
export function box(p: Pose, length: number, width: number, right = 0, forward = 0): LngLat[] {
  const corners: [number, number][] = [[-length / 2, -width / 2], [length / 2, -width / 2],
    [length / 2, width / 2], [-length / 2, width / 2], [-length / 2, -width / 2]]
  return corners.map(([f, r]) => offset(p, forward + f, right + r))
}

export function feature(ring: LngLat[], props: Record<string, unknown> = {}) {
  return { type: 'Feature' as const, properties: props,
    geometry: { type: 'Polygon' as const, coordinates: [ring] } }
}

export function collection(features: ReturnType<typeof feature>[]) {
  return { type: 'FeatureCollection' as const, features }
}
