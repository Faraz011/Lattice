// The AML world: two weeks of a small bank, transfer by transfer (lens/public/episodes/aml.json,
// built by src/lattice/lens/train.py). After each transfer the account check runs on every
// account whose features changed; an agent freezes an account once the check is confident it
// is laundering, and a frozen account's later transfers are blocked.
import { forward, type Ablation, type Net } from '../model/net'

export interface EpisodeAccount {
  id: string
  kind: string
  owner: string
  country: string
  city: string
  currency: string
  iban: string
  lng: number
  lat: number
}

// How a bank would name the transfer's method.
export function method(channel: string, from?: EpisodeAccount, to?: EpisodeAccount): string {
  if (channel === 'wire') {
    if (from && to && from.country !== to.country) return 'SWIFT wire'
    return from?.country === 'GB' ? 'Faster Payments' : 'SEPA transfer'
  }
  return ({ card: 'Card payment', cash_deposit: 'Cash deposit', p2p: 'P2P app',
    crypto: 'Crypto exchange' } as Record<string, string>)[channel] ?? channel
}

export function money(amount: number, currency = 'EUR'): string {
  return amount.toLocaleString('en-GB', { style: 'currency', currency, maximumFractionDigits: 0 })
}
export interface EpisodeStep {
  t: string
  tx: { id: string; src: string; dst: string; amount: number; channel: string }
  features: Record<string, number[]>
}
export interface Episode {
  title: string
  start: string
  end: string
  accounts: EpisodeAccount[]
  shared_devices: Record<string, string[]>
  steps: EpisodeStep[]
  cases: { kind: string; category: string; accounts: string[]; seed: string }[]
}

export interface Verdict { choice: number; confidence: number }

export interface Action {
  account: string
  verdict: string
  confidence: number
  step: number
  time: string
}

export interface Bank {
  step: number // transfers played so far
  features: Map<string, number[]>
  verdicts: Map<string, Verdict>
  frozen: Map<string, Action>
  blocked: Set<string> // transfer ids stopped by a freeze
  log: Action[]
  focus: string | null // the account whose decision is being traced
}

export const FREEZE_AT = 0.9

export function newBank(): Bank {
  return { step: 0, features: new Map(), verdicts: new Map(), frozen: new Map(),
    blocked: new Set(), log: [], focus: null }
}

export async function loadEpisode(): Promise<Episode> {
  const res = await fetch(`${import.meta.env.BASE_URL}episodes/aml.json`)
  if (!res.ok) throw new Error(`Could not load the bank episode (${res.status}).`)
  return res.json()
}

function judge(net: Net, x: number[], ablation: Ablation): Verdict {
  const run = forward(net, x, ablation)
  return { choice: run.choice, confidence: run.probs[run.choice] }
}

// Re-run the check on every account, e.g. after neurons are switched off on the trace device.
export function rejudge(bank: Bank, net: Net, ablation: Ablation): void {
  for (const [a, x] of bank.features) bank.verdicts.set(a, judge(net, x, ablation))
}

// Play one transfer. Returns the accounts whose verdict changed.
export function advance(bank: Bank, ep: Episode, net: Net, ablation: Ablation): string[] {
  if (bank.step >= ep.steps.length) return []
  const s = ep.steps[bank.step]
  if (bank.frozen.has(s.tx.src)) bank.blocked.add(s.tx.id)
  const changed: string[] = []
  for (const [a, x] of Object.entries(s.features)) {
    bank.features.set(a, x)
    const before = bank.verdicts.get(a)
    const v = judge(net, x, ablation)
    bank.verdicts.set(a, v)
    if (!before || before.choice !== v.choice) changed.push(a)
    if (v.choice !== 0 && v.confidence >= FREEZE_AT && !bank.frozen.has(a)) {
      const action = { account: a, verdict: net.outputs[v.choice].label, confidence: v.confidence,
        step: bank.step, time: s.t }
      bank.frozen.set(a, action)
      bank.log.push(action)
    }
  }
  // Trace what just changed most: a newly flagged account first, else the transfer's sender.
  const flagged = changed.filter((a) => (bank.verdicts.get(a)?.choice ?? 0) !== 0)
  if (flagged.length) bank.focus = flagged[0]
  else if (!bank.focus) bank.focus = s.tx.src
  bank.step++
  return changed
}

export function describeAccount(bank: Bank, ep: Episode, net: Net, a: string): string[] {
  const acct = ep.accounts.find((x) => x.id === a)
  const v = bank.verdicts.get(a)
  const out = [`${acct?.owner ?? 'Unknown'}, ${acct?.kind ?? 'account'} account`]
  if (v) out.push(`check says ${net.outputs[v.choice].label} (${Math.round(v.confidence * 100)}%)`)
  const f = bank.frozen.get(a)
  if (f) out.push(`frozen by the agent at transfer ${f.step + 1}`)
  return out
}

export const shortId = (id: string) => `acct_${id.slice(-6)}`
