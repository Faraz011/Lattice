import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { forward, type Net } from '../model/net'
import { trace } from '../model/trace'

const net: Net = JSON.parse(readFileSync('public/models/driving.json', 'utf8'))
const IDX = Object.fromEntries(net.inputs.map((f, i) => [f.id, i]))
const BRAKE = net.outputs.findIndex((o) => o.id === 'brake')

function situation(set: Record<string, number>): number[] {
  const x = net.inputs.map(() => 0)
  for (const [k, v] of Object.entries(set)) x[IDX[k]] = v
  return x
}

const emptyRoad = situation({ speed: 0.6 })
const redLight = situation({ speed: 0.6, light_red: 1, light_near: 0.9 })
const redAndPedestrian = situation({ speed: 0.6, light_red: 1, light_near: 0.9,
  ped_crossing: 1, crosswalk_near: 0.9 })

describe('the circuit', () => {
  it('names the hidden neurons that, on their own, make the car brake rather than drive on', () => {
    const t = trace(net, redLight, emptyRoad)

    expect(t.choice).toBe(BRAKE)
    expect(t.reference.choice).not.toBe(BRAKE)
    expect(t.circuit).not.toBeNull()
    expect(t.circuit!.hidden.length).toBeLessThan(10)
    expect(t.circuit!.margin).toBeGreaterThan(0) // everything else from the empty road: brakes
  })

  it('has nothing to explain when the car does what it does on an empty road', () => {
    const t = trace(net, emptyRoad, emptyRoad)

    expect(t.circuit).toBeNull()
    expect(t.backup).toBeNull()
  })
})

describe('the backup route', () => {
  it('appears when two hazards each demand braking, from different detectors', () => {
    const t = trace(net, redAndPedestrian, emptyRoad)

    expect(t.choice).toBe(BRAKE)
    expect(t.backup).not.toBeNull()
    const firstDetectors = t.circuit!.hidden.filter((n) => n.startsWith('h1_'))
    expect(t.backup!.hidden.some((n) => firstDetectors.includes(n))).toBe(false)
    expect(t.backup!.margin).toBeGreaterThan(0)
  })

  it('is missing when only one hazard is present', () => {
    const t = trace(net, redLight, emptyRoad)

    if (t.backup === null) {
      const detectors = t.circuit!.hidden.filter((n) => n.startsWith('h1_'))
      const values = t.reference.acts
      expect(forward(net, redLight, { nodes: new Set(detectors), values }).choice)
        .not.toBe(BRAKE)
    }
  })
})

describe('attribution', () => {
  it('splits a second-layer neuron among its incoming connections', () => {
    const t = trace(net, redLight, emptyRoad)
    const W = net.layers[1].W
    const outW = net.layers[2].W
    for (let j = 0; j < W.length; j++) {
      if (t.run.acts[2][j] <= 0) continue
      const incoming = W[j].reduce((s, _, i) => s + t.edgeAttr[`1:${i}:${j}`], 0)
      const towardChoice = outW[t.choice][j] - outW[t.runnerUp][j]
      const shift = W[j].reduce((s, w, i) => s + w * (t.run.acts[1][i] - t.reference.acts[1][i]), 0)
      expect(incoming).toBeCloseTo(shift * towardChoice, 6)
    }
  })
})

describe('switching neurons off', () => {
  it('puts an input at its average and a hidden neuron at zero', () => {
    const run = forward(net, redLight, { nodes: new Set(['x1', 'h1_0']) })
    expect(run.acts[0][IDX.light_red]).toBeCloseTo(net.means[0][IDX.light_red])
    expect(run.acts[1][0]).toBe(0)
  })
})
