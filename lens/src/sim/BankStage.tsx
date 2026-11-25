// Two weeks of a European bank, transfer by transfer, on a map of its customers' cities with a
// live ledger beneath. Accounts take the colour of the network's verdict; the agent freezes one
// once the verdict is confident; a frozen account's transfers are blocked. Click an account, on
// the map or in the ledger, to trace its decision on the other device.
import { useEffect, useMemo, useRef, useState } from 'react'

import type { Message } from '../link'
import type { Net } from '../model/net'
import {
  advance, describeAccount, FREEZE_AT, method, money, newBank, rejudge, shortId, type Bank,
  type Episode,
} from './aml'
import { BankMap } from './BankMap'

const SPEEDS = [{ label: '1x', ms: 1400 }, { label: '3x', ms: 450 }]

interface Props {
  net: Net & { reference: number[] }
  episode: Episode
  off: string[]
  send: (m: Message) => void
}

export function BankStage({ net, episode, off, send }: Props) {
  const bank = useRef<Bank>(newBank())
  const [tick, setTick] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(0)
  const [showKey, setShowKey] = useState(false)
  const ablation = useMemo(() => ({ nodes: new Set(off) }), [off])
  const refresh = () => setTick((t) => t + 1)

  const owners = useMemo(() => new Map(episode.accounts.map((a) => [a.id, a])), [episode])
  const planted = useMemo(() => new Map(episode.cases.flatMap((c) =>
    c.accounts.map((a) => [a, c] as const))), [episode])

  // Neurons switched off on the trace device: every account is judged again, at once.
  useEffect(() => {
    rejudge(bank.current, net, ablation)
    refresh()
  }, [net, ablation])

  useEffect(() => {
    if (!playing) return
    const id = window.setInterval(() => {
      if (bank.current.step >= episode.steps.length) { setPlaying(false); return }
      advance(bank.current, episode, net, ablation)
      refresh()
    }, SPEEDS[speed].ms)
    return () => window.clearInterval(id)
  }, [playing, speed, episode, net, ablation])

  const b = bank.current
  const focus = b.focus

  // Share the traced account with the trace device.
  useEffect(() => {
    if (!focus) return
    const x = b.features.get(focus)
    if (!x) return
    send({ type: 'scene', scenario: 'aml', x, reference: net.reference,
      title: `${shortId(focus)}, ${owners.get(focus)?.owner ?? ''}`,
      context: describeAccount(b, episode, net, focus), at: Date.now() })
  })

  const current = b.step > 0 ? episode.steps[b.step - 1] : null
  const when = current ? new Date(current.t) : new Date(episode.start)

  return (
    <div className="sim">
      <div className="stage bank">
        <BankMap bank={b} episode={episode} version={tick} answerKey={showKey ? planted : null}
          onFocus={(a) => { b.focus = a; refresh() }} />
        <Ledger bank={b} episode={episode} net={net}
          onFocus={(a) => { b.focus = a; refresh() }} />
      </div>
      <aside className="side">
        <section>
          <h3>{when.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}
            , {when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</h3>
          <p className="muted">Transfer {b.step} of {episode.steps.length}.
            {current && <> {shortId(current.tx.src)} sent {money(current.tx.amount)} to{' '}
              {shortId(current.tx.dst)} by {current.tx.channel}.</>}</p>
          <div className="controls" style={{ marginTop: '0.5rem' }}>
            <button type="button" className="primary" onClick={() => setPlaying((p) => !p)}
              disabled={b.step >= episode.steps.length}>{playing ? 'Pause' : 'Play'}</button>
            <button type="button" onClick={() => { advance(b, episode, net, ablation); refresh() }}
              disabled={playing || b.step >= episode.steps.length}>Next transfer</button>
            <button type="button" onClick={() => setSpeed((s) => (s + 1) % SPEEDS.length)}>
              Speed {SPEEDS[speed].label}</button>
            <button type="button" className="quiet" onClick={() => {
              bank.current = newBank(); setPlaying(true); refresh()
            }}>Start over</button>
          </div>
        </section>
        {off.length > 0 && (
          <p className="banner" role="status">
            {off.length} {off.length === 1 ? 'neuron is' : 'neurons are'} switched off from the
            trace device. Every account has been checked again without {off.length === 1 ? 'it' : 'them'}.
          </p>
        )}
        <section>
          <h3>Traced on the other device</h3>
          {focus ? <ul className="facts">{describeAccount(b, episode, net, focus).map((f) =>
            <li key={f}>{f}</li>)}</ul> : <p className="muted">Click an account.</p>}
        </section>
        <section>
          <h3>The agent's actions</h3>
          <p className="muted">It freezes an account when the check is at least
            {' '}{Math.round(FREEZE_AT * 100)}% sure it is laundering.</p>
          {b.log.length === 0 ? <p className="muted">Nothing frozen yet.</p> : (
            <ul className="log">
              {[...b.log].reverse().map((a) => (
                <li key={a.account}>
                  <button type="button" className="quiet" onClick={() => { b.focus = a.account; refresh() }}>
                    Froze {shortId(a.account)}</button>: {a.verdict}, {Math.round(a.confidence * 100)}%
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <label className="muted">
            <input type="checkbox" checked={showKey} onChange={(e) => setShowKey(e.target.checked)} />
            {' '}Show the planted cases (the answer key: the network never sees it)
          </label>
        </section>
      </aside>
    </div>
  )
}

// The live ledger: the newest transfers first, as a bank's operations screen would list them.
function Ledger({ bank, episode, net, onFocus }: {
  bank: Bank; episode: Episode; net: Net; onFocus: (a: string) => void
}) {
  const accounts = new Map(episode.accounts.map((a) => [a.id, a]))
  const rows = episode.steps.slice(Math.max(0, bank.step - 9), bank.step).reverse()
  const party = (id: string) => {
    const a = accounts.get(id)
    const v = bank.verdicts.get(id)
    const flagged = v && v.choice !== 0
    return (
      <button type="button" className={`party${flagged ? ' flagged' : ''}${bank.frozen.has(id) ? ' frozen' : ''}`}
        onClick={() => onFocus(id)} title={`Trace ${a?.owner ?? id} on the other device`}>
        <strong>{a?.owner ?? shortId(id)}</strong>
        <span>{a?.city} · {a?.iban}</span>
      </button>
    )
  }
  return (
    <div className="ledger" role="region" aria-label="Transactions, newest first">
      <table>
        <thead>
          <tr><th>Time</th><th>From</th><th>To</th><th className="num">Amount</th><th>Method</th>
            <th>Status</th></tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={6} className="muted">Press Play to open the bank.</td></tr>}
          {rows.map((s) => {
            const from = accounts.get(s.tx.src)
            const to = accounts.get(s.tx.dst)
            const blocked = bank.blocked.has(s.tx.id)
            const review = [s.tx.src, s.tx.dst].some((a) => (bank.verdicts.get(a)?.choice ?? 0) !== 0)
            const verdict = [s.tx.src, s.tx.dst].map((a) => bank.verdicts.get(a))
              .find((v) => v && v.choice !== 0)
            return (
              <tr key={s.tx.id} className={blocked ? 'blocked' : review ? 'review' : undefined}>
                <td>{new Date(s.t).toLocaleString('en-GB', { weekday: 'short', hour: '2-digit',
                  minute: '2-digit' })}</td>
                <td>{party(s.tx.src)}</td>
                <td>{party(s.tx.dst)}</td>
                <td className="num">{money(s.tx.amount, from?.currency)}</td>
                <td>{method(s.tx.channel, from, to)}</td>
                <td><span className="status">{blocked ? 'Blocked: sender frozen' : review
                  ? `Under review: ${net.outputs[verdict!.choice].label}` : 'Cleared'}</span></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
