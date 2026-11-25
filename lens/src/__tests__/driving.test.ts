import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { Net } from '../model/net'
import { trace } from '../model/trace'
import {
  cutIn, features, newWorld, reference, rel, step, stepOut, worldFromMap, type Physics,
  type RouteMap,
} from '../sim/driving'

const net: Net = JSON.parse(readFileSync('public/models/driving.json', 'utf8'))
const physics = net.physics as unknown as Physics

function drive(seconds: number, nodes: string[] = [], events = false) {
  const w = newWorld(7)
  let seed = 3
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
  for (let t = 0; t < seconds / physics.tick_s; t++) {
    if (events && t % 300 === 150) stepOut(w, physics)
    if (events && t % 700 === 400) cutIn(w)
    step(w, physics, net, { nodes: new Set(nodes) }, undefined, rand)
  }
  return w
}

describe('the car on its own network', () => {
  it('gets down the road through lights, crosswalks and cars without an incident', () => {
    const w = drive(240, [], true)

    expect(w.car.at).toBeGreaterThan(1000)
    expect(w.incidents, JSON.stringify(w.incidents)).toEqual([])
  })

  it('features match the trained inputs: an empty road is all zeros but speed', () => {
    const w = newWorld(1)
    w.lights = []
    w.crosswalks = []
    const x = features(w, physics)
    expect(x).toHaveLength(net.inputs.length)
    expect(x.slice(1)).toEqual(net.inputs.slice(1).map(() => 0))
    expect(reference(x)).toEqual(x)
  })
})

describe('switching a detector off on the trace device', () => {
  it('makes the car run red lights when the red-light detector is gone', () => {
    const red = net.neurons.filter((n) => n.layer === 1 && /red light/.test(n.label)).map((n) => n.id)
    expect(red.length).toBeGreaterThan(0)

    const w = drive(240, red)

    expect(w.incidents.some((i) => i.kind === 'red_light')).toBe(true)
  })
})

describe('a live scene', () => {
  it('can be traced: approaching a red light the car brakes for a reason', () => {
    const w = newWorld(2)
    w.car.speed = 12
    w.lights = [{ at: 18, offset: 13 }] // red now
    w.crosswalks = []
    const x = features(w, physics)

    const t = trace(net, x, reference(x))

    expect(net.outputs[t.choice].id).toBe('brake')
    expect(t.circuit).not.toBeNull()
  })
})

describe('the London route', () => {
  const map: RouteMap = JSON.parse(readFileSync('public/maps/london.json', 'utf8'))

  it('places real junctions and crossings, and the car drives it in traffic without an incident', () => {
    const w = worldFromMap(map, 4)
    expect(w.lights.length).toBeGreaterThan(20)
    expect(w.crosswalks.length).toBeGreaterThan(20)
    expect(w.traffic.length).toBeGreaterThan(6)
    let seed = 11
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
    let tightest = Infinity
    for (let t = 0; t < 12_000; t++) { // 20 minutes
      if (t % 300 === 150) stepOut(w, physics)
      if (t % 900 === 450) cutIn(w, rand)
      step(w, physics, net, {}, undefined, rand)
      // No two cars in one lane ever overlap: bumper to bumper, a gap stays.
      for (const lane of [1, -1] as const) {
        const cars = w.traffic.filter((v) => v.lane === lane)
          .map((v) => ({ v, d: rel(w, v.at) * lane })).sort((a, b) => a.d - b.d)
        for (let k = 1; k < cars.length; k++) {
          tightest = Math.min(tightest, cars[k].d - cars[k - 1].d - cars[k].v.length)
        }
      }
    }
    expect(w.odometer).toBeGreaterThan(4000) // London traffic: about 20 km/h on average
    expect(w.car.at).toBeLessThan(map.length_m)
    expect(w.incidents, JSON.stringify(w.incidents)).toEqual([])
    expect(tightest).toBeGreaterThan(0)
  }, 60_000)
})
