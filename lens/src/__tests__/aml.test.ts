import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { Net } from '../model/net'
import { trace } from '../model/trace'
import { advance, newBank, rejudge, type Episode } from '../sim/aml'

const net: Net = JSON.parse(readFileSync('public/models/aml.json', 'utf8'))
const ep: Episode = JSON.parse(readFileSync('public/episodes/aml.json', 'utf8'))
const ref = (net as unknown as { reference: number[] }).reference

function play(nodes: string[] = []) {
  const bank = newBank()
  while (bank.step < ep.steps.length) advance(bank, ep, net, { nodes: new Set(nodes) })
  return bank
}

describe('two weeks of the bank', () => {
  it('freezes members of planted cases and no everyday account or decoy', () => {
    const bank = play()
    const planted = new Set(ep.cases.filter((c) => c.category === 'planted').flatMap((c) => c.accounts))

    expect(bank.frozen.size).toBeGreaterThan(5)
    expect([...bank.frozen.keys()].every((a) => planted.has(a))).toBe(true)
    // Every planted case is caught: at least one member frozen.
    for (const c of ep.cases.filter((c) => c.category === 'planted')) {
      expect(c.accounts.some((a) => bank.frozen.has(a))).toBe(true)
    }
  })

  it('blocks a frozen account\'s later transfers', () => {
    expect(play().blocked.size).toBeGreaterThan(0)
  })
})

describe('tracing a frozen account', () => {
  it('explains the verdict against an average clear account', () => {
    const bank = play()
    const [account] = bank.frozen.keys()

    const t = trace(net, bank.features.get(account)!, ref)

    expect(t.choice).not.toBe(0)
    expect(t.circuit).not.toBeNull()
  })

  it('switching the circuit\'s neurons off clears the account unless a backup route holds', () => {
    const bank = play()
    const [account] = bank.frozen.keys()
    const t = trace(net, bank.features.get(account)!, ref)

    rejudge(bank, net, { nodes: new Set(t.circuit!.hidden) })

    const v = bank.verdicts.get(account)!
    if (t.backup) expect(v.choice).toBe(t.choice)
    else expect(v.choice).not.toBe(t.choice)
  })
})
