// The self-driving car's world: a road with traffic lights, crosswalks and other cars. Positions
// are metres along the road; on a real route (lens/public/maps, from OpenStreetMap) the road is
// a loop and every distance is measured ahead of the car around it. Each tick the car reads the
// 13 numbers its network was trained on (src/lattice/lens/driving.py, INPUTS, same order and
// meaning) and acts.
import { forward, type Ablation, type Net } from '../model/net'

export interface Physics {
  view_m: number
  vmax_ms: number
  accel_ms2: number
  brake_ms2: number
  drag_ms2: number
  tick_s: number
}

export type Colour = 'red' | 'yellow' | 'green'

export interface Light { at: number; offset: number } // stop line position; cycle offset (s)
export interface Pedestrian { id: number; crosswalk: number; x: number; speed: number; wait: number }
export interface LeadCar { at: number; speed: number; target: number }
export type Incident = { kind: 'red_light' | 'pedestrian' | 'collision'; at: number; time: number }

export interface World {
  time: number
  length: number | null // a looping route's length; null for an endless straight road
  odometer: number // metres driven
  car: { at: number; speed: number }
  lights: Light[]
  crosswalks: number[]
  pedestrians: Pedestrian[]
  lead: LeadCar | null
  rain: boolean
  night: boolean
  action: number
  probs: number[]
  seen: number[] | null // the inputs the last decision was made on
  incidents: Incident[]
  nextId: number
}

export const ROAD_WIDTH = 7 // metres a pedestrian crosses
export const CYCLE = { green: 9, yellow: 4, red: 8 } // 4 s of yellow, as on a 50 km/h road
const PERIOD = CYCLE.green + CYCLE.yellow + CYCLE.red
export const ACTIONS = ['accelerate', 'cruise', 'brake'] as const

export function colourAt(light: Light, time: number, forced?: Map<number, Colour>): Colour {
  const f = forced?.get(light.at)
  if (f) return f
  const t = (((time + light.offset) % PERIOD) + PERIOD) % PERIOD
  return t < CYCLE.green ? 'green' : t < CYCLE.green + CYCLE.yellow ? 'yellow' : 'red'
}

export function newWorld(seed = 1): World {
  const rand = mulberry(seed)
  const lights: Light[] = []
  const crosswalks: number[] = []
  for (let i = 0; i < 60; i++) {
    const at = 160 + i * 230
    lights.push({ at, offset: rand() * PERIOD })
    crosswalks.push(at + 6) // a crosswalk just past each stop line
    if (rand() < 0.6) crosswalks.push(at + 100 + rand() * 60) // and some mid-block ones
  }
  crosswalks.sort((a, b) => a - b)
  return blank(lights, crosswalks, null)
}

// A real route: its signalled junctions and crossings, as metres along it.
export interface RouteMap {
  name: string
  source: string
  length_m: number
  route: [number, number][]
  cumulative_m: number[]
  signals: { at: number; lng: number; lat: number }[]
  crossings: { at: number; lng: number; lat: number; kind: string }[]
}

export function worldFromMap(map: RouteMap, seed = 1): World {
  const rand = mulberry(seed)
  const lights = map.signals.map((sig) => ({ at: sig.at, offset: rand() * PERIOD }))
  // Several crossing nodes on one crossing (each half of a divided road): keep one per 12 m.
  const crosswalks: number[] = []
  for (const c of map.crossings) {
    if (!crosswalks.length || c.at - crosswalks[crosswalks.length - 1] > 12) crosswalks.push(c.at)
  }
  return blank(lights, crosswalks, map.length_m)
}

function blank(lights: Light[], crosswalks: number[], length: number | null): World {
  return { time: 0, length, odometer: 0, car: { at: 0, speed: 8 }, lights, crosswalks,
    pedestrians: [], lead: null, rain: false, night: false, action: 1, probs: [0, 1, 0],
    seen: null, incidents: [], nextId: 1 }
}

// How far `at` is ahead of the car: negative behind it. Around a loop, the nearer way round.
export function rel(w: World, at: number): number {
  let d = at - w.car.at
  if (w.length) {
    d = ((d % w.length) + w.length) % w.length
    if (d > w.length / 2) d -= w.length
  }
  return d
}

function mulberry(seed: number) {
  let a = seed >>> 0
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const ahead = (w: World, at: number, view: number) => rel(w, at) > 0 && rel(w, at) <= view
const nearest = <T>(w: World, items: T[], at: (t: T) => number, view: number): T | null => {
  let best: T | null = null
  for (const t of items) {
    if (ahead(w, at(t), view) && (best === null || rel(w, at(t)) < rel(w, at(best)))) best = t
  }
  return best
}

export function nextLight(w: World, p: Physics): Light | null {
  return nearest(w, w.lights, (l) => l.at, p.view_m)
}

export function nextCrosswalk(w: World, p: Physics): number | null {
  return nearest(w, w.crosswalks, (c) => c, p.view_m)
}

export const onCrosswalk = (ped: Pedestrian) => ped.wait <= 0 && ped.x >= 0 && ped.x <= ROAD_WIDTH
export const atCurb = (ped: Pedestrian) => ped.wait > 0

// The 13 inputs, in the order of driving.py's INPUTS.
export function features(w: World, p: Physics, forced?: Map<number, Colour>): number[] {
  const near = (d: number) => Math.max(0, 1 - d / p.view_m)
  const light = nextLight(w, p)
  const colour = light ? colourAt(light, w.time, forced) : null
  const cw = nextCrosswalk(w, p)
  const peds = cw === null ? [] : w.pedestrians.filter((x) => x.crosswalk === cw)
  const lead = w.lead && ahead(w, w.lead.at, p.view_m) ? w.lead : null
  return [
    Math.min(1, w.car.speed / p.vmax_ms),
    colour === 'red' ? 1 : 0,
    colour === 'yellow' ? 1 : 0,
    colour === 'green' ? 1 : 0,
    light ? near(rel(w, light.at)) : 0,
    peds.some(onCrosswalk) ? 1 : 0,
    peds.some(atCurb) ? 1 : 0,
    cw === null ? 0 : near(rel(w, cw)),
    lead ? 1 : 0,
    lead ? near(rel(w, lead.at)) : 0,
    lead ? Math.min(1, Math.max(0, (w.car.speed - lead.speed) / p.vmax_ms)) : 0,
    w.rain ? 1 : 0,
    w.night ? 1 : 0,
  ]
}

// The same moment with the road emptied: what the tracer compares a decision with.
export function reference(x: number[]): number[] {
  return x.map((v, i) => (i === 0 || i === 11 || i === 12 ? v : 0))
}

export function describe(w: World, p: Physics, forced?: Map<number, Colour>): string[] {
  const out = [`${Math.round(w.car.speed * 3.6)} km/h${w.rain ? ', wet road' : ''}${w.night ? ', night' : ''}`]
  const light = nextLight(w, p)
  if (light) out.push(`${colourAt(light, w.time, forced)} light in ${Math.round(rel(w, light.at))} m`)
  const cw = nextCrosswalk(w, p)
  if (cw !== null) {
    const peds = w.pedestrians.filter((x) => x.crosswalk === cw)
    const who = peds.some(onCrosswalk) ? ', someone crossing' : peds.some(atCurb)
      ? ', someone waiting' : ''
    out.push(`crosswalk in ${Math.round(rel(w, cw))} m${who}`)
  }
  if (w.lead && ahead(w, w.lead.at, p.view_m)) {
    out.push(`car ahead at ${Math.round(rel(w, w.lead.at))} m, ${Math.round(w.lead.speed * 3.6)} km/h`)
  }
  return out
}

// Scripted events the presenter triggers from the simulation screen.
export function stepOut(w: World, p: Physics): void {
  const cw = w.crosswalks.find((c) => rel(w, c) > 25 && rel(w, c) < p.view_m)
  if (cw === undefined) return
  w.pedestrians.push({ id: w.nextId++, crosswalk: cw, x: -0.5, speed: 1.3, wait: 0.6 })
}

export function cutIn(w: World): void {
  w.lead = { at: w.car.at + 30, speed: Math.max(3, w.car.speed * 0.45), target: 6 }
}

export function step(w: World, p: Physics, net: Net, ablation: Ablation,
  forced?: Map<number, Colour>, rand: () => number = Math.random): number[] {
  const dt = p.tick_s
  const x = features(w, p, forced)
  const run = forward(net, x, ablation)
  w.action = run.choice
  w.probs = run.probs
  w.seen = x
  const accel = run.choice === 0 ? p.accel_ms2 : run.choice === 2 ? -p.brake_ms2 * (w.rain ? 0.7 : 1)
    : -p.drag_ms2
  w.car.speed = Math.min(p.vmax_ms, Math.max(0, w.car.speed + accel * dt))
  const moved = w.car.speed * dt
  // Passed during this tick: ahead of the car by no more than it moved.
  const passes = (at: number) => { const d = rel(w, at); return d > 0 && d <= moved }
  const passedLights = w.lights.filter((l) => passes(l.at))
  const passedPeds = w.pedestrians.filter((ped) => passes(ped.crosswalk))
  w.car.at += moved
  if (w.length) w.car.at %= w.length
  w.odometer += moved
  w.time += dt

  // What happened, judged against the world, not the network.
  for (const l of passedLights) {
    if (colourAt(l, w.time, forced) === 'red') {
      w.incidents.push({ kind: 'red_light', at: l.at, time: w.time })
    }
  }
  for (const ped of passedPeds) {
    if (onCrosswalk(ped)) {
      w.incidents.push({ kind: 'pedestrian', at: ped.crosswalk, time: w.time })
      ped.x = ROAD_WIDTH + 1 // they jump clear; the incident is what counts
    }
  }

  for (const ped of w.pedestrians) {
    if (ped.wait > 0) ped.wait -= dt
    else ped.x += ped.speed * dt
  }
  w.pedestrians = w.pedestrians.filter((ped) => ped.x < ROAD_WIDTH + 2 && rel(w, ped.crosswalk) > -30)
  // Now and then someone comes to a crosswalk ahead on their own.
  if (rand() < dt * 0.05) stepOut(w, p)

  if (w.lead) {
    const l = w.lead
    if (l.target < 12 && Math.abs(l.speed - l.target) < 0.2 && rand() < dt * 0.15) l.target = 14
    l.speed += Math.sign(l.target - l.speed) * Math.min(Math.abs(l.target - l.speed), 1.5 * dt)
    l.at += l.speed * dt
    if (w.length) l.at %= w.length
    if (rel(w, l.at) < 3 && w.car.speed > l.speed) {
      w.incidents.push({ kind: 'collision', at: l.at, time: w.time })
      w.car.speed = l.speed
    }
    if (rel(w, l.at) > p.view_m * 1.4) w.lead = null
  }
  return x
}
