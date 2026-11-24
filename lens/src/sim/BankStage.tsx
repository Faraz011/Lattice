// Two weeks of a small bank, transfer by transfer. Accounts take the colour of the network's
// verdict; the agent freezes one once the verdict is confident; a frozen account's transfers are
// blocked. Click an account to trace its decision on the other device.
import { useEffect, useMemo, useRef, useState } from 'react'

import type { Message } from '../link'
import type { Net } from '../model/net'
import {
  advance, describeAccount, FREEZE_AT, newBank, rejudge, shortId, type Bank, type Episode,
} from './aml'
import { layout } from './layout'

const W = 1000
const H = 680
const SPEEDS = [{ label: '1x', ms: 1400 }, { label: '3x', ms: 450 }]

interface Props {
  net: Net & { reference: number[] }
  episode: Episode
  off: string[]
  send: (m: Message) => void
}

export function BankStage({ net, episode, off, send }: Props) {
  const bank = useRef<Bank>(newBank())
  const [, setTick] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(0)
  const [showKey, setShowKey] = useState(false)
  const ablation = useMemo(() => ({ nodes: new Set(off) }), [off])
  const refresh = () => setTick((t) => t + 1)

  const pos = useMemo(() => layout(episode.accounts.map((a) => a.id),
    episode.steps.map((s) => [s.tx.src, s.tx.dst] as [string, string]), W, H), [episode])
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

  const shown = episode.steps.slice(0, b.step)
  const current = b.step > 0 ? episode.steps[b.step - 1] : null
  const when = current ? new Date(current.t) : new Date(episode.start)

  return (
    <div className="sim">
      <div className="stage bank">
        <svg viewBox={`0 0 ${W} ${H}`} className="diagram" role="img"
          aria-label={`Accounts and transfers, ${b.step} of ${episode.steps.length} played`}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5"
              orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#4b5670" /></marker>
          </defs>
          {Object.entries(episode.shared_devices).flatMap(([a, others]) => others.filter((o) => o > a)
            .map((o) => {
              const p = pos.get(a)!, q = pos.get(o)!
              return <line key={`d-${a}-${o}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke="#85661c"
                strokeWidth={1} strokeDasharray="2 4" opacity={0.6} />
            }))}
          {shown.map((s, i) => {
            const p = pos.get(s.tx.src)!, q = pos.get(s.tx.dst)!
            const recent = b.step - i <= 6
            const blocked = b.blocked.has(s.tx.id)
            return <line key={s.tx.id} x1={p.x} y1={p.y} x2={q.x} y2={q.y}
              stroke={blocked ? '#a3233a' : '#4b5670'} strokeWidth={recent ? 2 : 1}
              strokeDasharray={blocked ? '6 4' : undefined}
              opacity={recent ? 0.9 : 0.25} markerEnd={recent ? 'url(#arrow)' : undefined} />
          })}
          {current && (() => {
            const p = pos.get(current.tx.src)!, q = pos.get(current.tx.dst)!
            const blocked = b.blocked.has(current.tx.id)
            return (
              <g key={`move-${b.step}`}>
                <circle r={7} fill={blocked ? '#a3233a' : '#85661c'}>
                  <animateMotion dur="0.8s" fill="freeze" path={`M${p.x},${p.y} L${q.x},${q.y}`} />
                </circle>
                <text x={(p.x + q.x) / 2 + 8} y={(p.y + q.y) / 2 - 8} className="label">
                  {blocked ? 'blocked: account frozen' : money(current.tx.amount)}</text>
              </g>
            )
          })()}
          {episode.accounts.map((a) => {
            const p = pos.get(a.id)!
            const v = b.verdicts.get(a.id)
            const flagged = v && v.choice !== 0
            const frozen = b.frozen.has(a.id)
            const isFocus = a.id === focus
            const key = showKey ? planted.get(a.id) : undefined
            return (
              <g key={a.id} className="neuron" tabIndex={0} role="button"
                aria-label={`${shortId(a.id)}, ${a.owner}${flagged ? `, flagged ${net.outputs[v!.choice].label}` : ''}${frozen ? ', frozen' : ''}`}
                onClick={() => { b.focus = a.id; refresh() }}
                onKeyDown={(e) => { if (e.key === 'Enter') { b.focus = a.id; refresh() } }}>
                {key && <circle cx={p.x} cy={p.y} r={16} fill="none"
                  stroke={key.category === 'planted' ? '#a3233a' : '#2f6b4f'} strokeDasharray="3 3" />}
                {isFocus && <circle cx={p.x} cy={p.y} r={13} fill="none" stroke="#85661c" strokeWidth={3} />}
                {frozen
                  ? <rect x={p.x - 8} y={p.y - 8} width={16} height={16} rx={3} fill="#a3233a" />
                  : <circle cx={p.x} cy={p.y} r={a.kind === 'person' ? 6 : 8}
                    fill={flagged ? '#a3233a' : a.kind === 'person' ? '#f6f8f3' : '#dee6dc'}
                    stroke="#1e2942" strokeWidth={1.5} opacity={flagged ? Math.max(0.5, v!.confidence) : 1} />}
                {(flagged || isFocus || a.kind !== 'person') && (
                  <text x={p.x + 11} y={p.y + 4} className={flagged ? 'label' : 'label soft'}>
                    {a.kind !== 'person' ? a.owner : shortId(a.id)}
                    {flagged ? `: ${net.outputs[v!.choice].label}` : ''}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
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

const money = (n: number) => n.toLocaleString(undefined, { style: 'currency', currency: 'USD',
  maximumFractionDigits: 0 })
