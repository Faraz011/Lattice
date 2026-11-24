import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { Net } from '../model/net'
import { trace } from '../model/trace'
import { cutIn, features, newWorld, reference, step, stepOut, type Physics } from '../sim/driving'

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
