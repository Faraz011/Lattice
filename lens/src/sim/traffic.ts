// Other traffic on the route, driven by the Intelligent Driver Model (Treiber, Hennecke and
// Helbing, 2000): the standard car-following model behind smooth, human-like traffic. Each car
// accelerates toward its own desired speed, keeps a safe time gap to whatever is ahead (a car,
// our car, a red light's stop line, someone on a crossing) and brakes smoothly to stop behind it.
//
// Three streams: cars in our lane (the nearest one ahead is the "car ahead" our car's network
// sees), oncoming cars in the other lane, and cars crossing a junction while our light is red.
import { colourAt, onCrosswalk, rel, type Colour, type World } from './driving'

export interface Vehicle {
  id: number
  at: number // metres along the route (front bumper)
  prev: number // where it was one tick ago, for smooth drawing between ticks
  speed: number
  lane: 1 | -1 // 1: our direction, -1: oncoming
  v0: number // desired speed, m/s
  slowUntil: number // a car that cut in drives slowly until this time
  length: number
  color: string
}

export interface CrossCar {
  id: number
  junction: number // the junction's stop line, metres along the route
  x: number // metres across the route: from -40 to 40 (or back)
  prevX: number
  dir: 1 | -1
  speed: number
  color: string
}

// IDM parameters for city driving.
const A = 1.4 // comfortable acceleration, m/s2
const B = 2.2 // comfortable braking, m/s2
const S0 = 2.5 // standstill gap, m
const T = 1.3 // time gap, s
const COLOURS = ['#c9ced8', '#20242c', '#7d8799', '#a3233a', '#2f4f8f', '#e8e6df', '#5e6b52', '#b87333']
const OUR_LANE = 6
const ONCOMING = 6

export function idm(v: number, v0: number, gap: number, dv: number): number {
  const sStar = S0 + Math.max(0, v * T + (v * dv) / (2 * Math.sqrt(A * B)))
  return A * (1 - (v / Math.max(v0, 0.1)) ** 4 - (sStar / Math.max(gap, 0.1)) ** 2)
}

export function seedTraffic(w: World, rand: () => number): void {
  w.traffic = []
  const ahead = [70, 150, 240, 330, -70, -160]
  for (let k = 0; k < OUR_LANE; k++) w.traffic.push(car(w, 1, w.car.at + ahead[k], rand))
  for (let k = 0; k < ONCOMING; k++) w.traffic.push(car(w, -1, w.car.at - 300 + k * 110, rand))
}

function car(w: World, lane: 1 | -1, at: number, rand: () => number): Vehicle {
  const v0 = 10 + rand() * 4 // 36 to 50 km/h
  const pos = w.length ? ((at % w.length) + w.length) % w.length : at
  return { id: w.nextId++, at: pos, prev: pos, speed: v0 * 0.8, lane, v0, slowUntil: 0,
    length: 4.4 + rand() * 0.8, color: COLOURS[Math.floor(rand() * COLOURS.length)] }
}

// A slow car pulls in 30 m ahead of ours. If a car is already near that spot, it is the one
// that suddenly slows down instead: either way our car meets a slow car close ahead.
export function cutIn(w: World, rand: () => number = Math.random): void {
  const near = w.traffic.find((v) => v.lane === 1 && Math.abs(rel(w, v.at) - 30) < 18)
  const c = near ?? car(w, 1, w.car.at + 30, rand)
  c.speed = Math.min(c.speed, Math.max(3, w.car.speed * 0.45))
  c.slowUntil = w.time + 6
  if (!near) w.traffic.push(c)
}

// The nearest car ahead of ours in our lane, within `view` metres.
export function leadOf(w: World, view: number): Vehicle | null {
  let best: Vehicle | null = null
  for (const v of w.traffic) {
    if (v.lane !== 1) continue
    const d = rel(w, v.at)
    if (d > 0 && d <= view && (!best || d < rel(w, best.at))) best = v
  }
  return best
}

// What a car at `at`, going `lane`, must stop behind: the nearest obstacle ahead of it.
function obstacle(w: World, me: Vehicle, forced?: Map<number, Colour>):
  { gap: number; speed: number } {
  const dir = me.lane
  const ahead = (at: number) => {
    let d = (at - me.at) * dir
    if (w.length) {
      d = ((d % w.length) + w.length) % w.length
      if (d > w.length / 2) d -= w.length
    }
    return d
  }
  let gap = Infinity
  let speed = 0
  const consider = (d: number, v: number) => { if (d > 0 && d < gap) { gap = d; speed = v } }
  for (const o of w.traffic) {
    if (o === me || o.lane !== dir) continue
    consider(ahead(o.at) - o.length, o.speed)
  }
  if (dir === 1) consider(ahead(w.car.at) - 4.6, w.car.speed) // our car, from behind it
  for (const l of w.lights) {
    // Oncoming traffic stops on the far side of the junction.
    const line = dir === 1 ? l.at : l.at + 14
    const colour = colourAt(l, w.time, forced)
    const d = ahead(line)
    const canStop = d > (me.speed * me.speed) / (2 * B * 1.5)
    if (colour === 'red' || (colour === 'yellow' && canStop)) consider(d - 1, 0)
  }
  for (const p of w.pedestrians) {
    if (onCrosswalk(p) || p.wait > 0) consider(ahead(p.crosswalk) - 2, 0)
  }
  return { gap, speed }
}

export function stepTraffic(w: World, dt: number, forced: Map<number, Colour> | undefined,
  rand: () => number): void {
  for (const v of w.traffic) {
    v.prev = v.at
    const { gap, speed } = obstacle(w, v, forced)
    const v0 = w.time < v.slowUntil ? 5 : v.v0
    const a = idm(v.speed, v0, gap, v.speed - speed)
    v.speed = Math.max(0, v.speed + Math.max(-9, a) * dt)
    v.at += v.lane * v.speed * dt
    if (w.length) v.at = ((v.at % w.length) + w.length) % w.length
  }
  // Keep traffic around our car: a car that falls far behind reappears far ahead, out of sight.
  for (const v of w.traffic) {
    const d = rel(w, v.at)
    const behind = v.lane === 1 ? d < -220 : d < -260
    const beyond = v.lane === 1 ? d > 360 : false
    if (behind || beyond) {
      const to = v.lane === 1 ? (behind ? 330 + rand() * 40 : -180) : 300 + rand() * 60
      const spot = w.car.at + to
      const clear = w.traffic.every((o) => o === v || o.lane !== v.lane
        || Math.abs(rel(w, o.at) - to) > 30)
      if (clear) {
        const fresh = car(w, v.lane, spot, rand)
        Object.assign(v, { ...fresh, id: v.id })
      }
    }
  }
  stepCross(w, dt, forced, rand)
}

// While our light is red, traffic crosses the junction ahead.
function stepCross(w: World, dt: number, forced: Map<number, Colour> | undefined,
  rand: () => number): void {
  for (const c of w.cross) {
    c.prevX = c.x
    c.x += c.dir * c.speed * dt
  }
  w.cross = w.cross.filter((c) => Math.abs(c.x) < 45 && rel(w, c.junction) > -40)
  const light = w.lights.find((l) => { const d = rel(w, l.at); return d > -5 && d < 220 })
  if (!light) return
  const red = colourAt(light, w.time, forced) === 'red'
  const busy = w.cross.some((c) => c.junction === light.at && Math.abs(c.x) > 30)
  if (red && !busy && rand() < dt * 0.55) {
    const dir: 1 | -1 = rand() < 0.5 ? 1 : -1
    w.cross.push({ id: w.nextId++, junction: light.at, x: -42 * dir, prevX: -42 * dir, dir,
      speed: 9 + rand() * 3, color: COLOURS[Math.floor(rand() * COLOURS.length)] })
  }
}
