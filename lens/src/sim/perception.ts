// What the car's cameras detect, drawn over the camera view the way an autonomous car's
// perception feed is: a box around every car, pedestrian and traffic light in view, with its
// distance. The ones the network's inputs come from (the next light, the next crossing's
// pedestrians, the car ahead) are drawn solid; everything else the cameras see is dashed.
import {
  colourAt, nextCrosswalk, nextLight, onCrosswalk, rel, ROAD_WIDTH, type Colour, type Physics, type World,
} from './driving'
import { leadOf } from './traffic'

export type Kind = 'car' | 'pedestrian' | 'red' | 'yellow' | 'green' | 'light-real' // a real light, colour unknown

// An object in the world, in route terms: `s` metres along the route, `right` metres to the
// right of the route's centre line (facing along the route), `height` metres tall.
export interface Seen {
  key: string
  kind: Kind
  s: number
  right: number
  base: number // metres above the ground where the object starts (a lamp sits up a pole)
  height: number
  width: number
  label: string
  used: boolean // one of the things the network's inputs are read from
}

// A box on the screen, in CSS pixels of the view.
export interface Box { key: string; kind: Kind; x: number; y: number; w: number; h: number; label: string; used: boolean }

const LANE = -1.9
const KERB = -6.5

export function seen(w: World, p: Physics, forced?: Map<number, Colour>): Seen[] {
  const out: Seen[] = []
  const view = p.view_m
  const lead = leadOf(w, view)
  const light = nextLight(w, p)
  const crossing = nextCrosswalk(w, p)
  const within = (s: number) => { const d = rel(w, s); return d > 2 && d < view + 20 }

  for (const v of w.traffic) {
    if (!within(v.at) && !(v.lane === -1 && rel(w, v.at) > 2 && rel(w, v.at) < view + 40)) continue
    const d = rel(w, v.at)
    out.push({ key: `car${v.id}`, kind: 'car', s: v.at, right: v.lane === 1 ? LANE : -LANE, base: 0,
      height: 1.5, width: 1.85, used: v === lead,
      label: `car ${Math.round(d)} m · ${Math.round(v.speed * 3.6)} km/h` })
  }
  for (const c of w.cross) {
    if (!within(c.junction)) continue
    out.push({ key: `x${c.id}`, kind: 'car', s: c.junction + 8, right: c.x, base: 0, height: 1.5,
      width: 4.4, used: false, label: `crossing car ${Math.round(rel(w, c.junction) + 8)} m` })
  }
  for (const ped of w.pedestrians) {
    if (!within(ped.crosswalk)) continue
    const across = ped.wait > 0 ? -7.5 : -6 + (ped.x / ROAD_WIDTH) * 12
    const what = onCrosswalk(ped) ? 'pedestrian crossing' : 'pedestrian waiting'
    out.push({ key: `p${ped.id}`, kind: 'pedestrian', s: ped.crosswalk, right: across, base: 0,
      height: 1.75, width: 0.6, used: ped.crosswalk === crossing,
      label: `${what} ${Math.round(rel(w, ped.crosswalk))} m` })
  }
  for (const l of w.lights) {
    if (!within(l.at)) continue
    const colour = colourAt(l, w.time, forced)
    out.push({ key: `l${l.at}`, kind: colour, s: l.at, right: KERB, base: 4, height: 1.2,
      width: 0.6, used: l === light, label: `${colour} light ${Math.round(rel(w, l.at))} m` })
  }
  return out
}

// Draws the boxes into `layer`, reusing its elements frame to frame.
export function drawBoxes(layer: HTMLElement | null, boxes: Box[]): void {
  if (!layer) return
  const pool = layer.children as HTMLCollectionOf<HTMLElement>
  while (pool.length < boxes.length) {
    const d = document.createElement('div')
    d.className = 'det'
    d.append(document.createElement('span'))
    layer.append(d)
  }
  for (let i = 0; i < pool.length; i++) {
    const el = pool[i]
    const b = boxes[i]
    if (!b) { el.style.display = 'none'; continue }
    el.style.display = ''
    el.className = `det ${b.kind}${b.used ? ' used' : ''}`
    el.style.transform = `translate(${Math.round(b.x - b.w / 2)}px, ${Math.round(b.y - b.h)}px)`
    el.style.width = `${Math.max(6, Math.round(b.w))}px`
    el.style.height = `${Math.max(6, Math.round(b.h))}px`
    const tag = el.firstElementChild as HTMLElement
    if (tag.textContent !== b.label) tag.textContent = b.label
  }
}
