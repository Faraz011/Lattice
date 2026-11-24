// The self-driving car, drawn from above. The car's network decides every 0.1 s; the presenter
// sets up hazards; the trace device gets the current moment four times a second.
import { useEffect, useMemo, useRef, useState } from 'react'

import type { Message } from '../link'
import type { Net } from '../model/net'
import {
  ACTIONS, colourAt, cutIn, describe, features, newWorld, nextLight, reference, ROAD_WIDTH, step,
  stepOut, type Colour, type Physics, type World,
} from './driving'

const INCIDENT_WORDS = {
  red_light: 'Ran a red light',
  pedestrian: 'Drove through a crosswalk with someone on it',
  collision: 'Hit the car ahead',
} as const

interface Props {
  net: Net
  off: string[]
  send: (m: Message) => void
}

export function DrivingStage({ net, off, send }: Props) {
  const physics = net.physics as unknown as Physics
  const world = useRef<World>(newWorld(1))
  const forced = useRef(new Map<number, Colour>())
  const forcedUntil = useRef(new Map<number, number>())
  const canvas = useRef<HTMLCanvasElement>(null)
  const [paused, setPaused] = useState(false)
  // Pause at a moment worth explaining: once braking is steady, or once the car has stopped.
  const [armed, setArmed] = useState<'brake' | 'stop' | null>(null)
  const braking = useRef(0) // consecutive ticks of braking
  const [, setFrame] = useState(0) // re-render the side panel a few times a second
  const ablation = useMemo(() => ({ nodes: new Set(off) }), [off])
  const live = useRef({ paused, ablation, armed })
  live.current = { paused, ablation, armed }

  // Simulation: fixed 0.1 s steps on a timer, so it keeps time when the tab is not in front.
  useEffect(() => {
    let last = performance.now()
    let acc = 0
    const id = window.setInterval(() => {
      const now = performance.now()
      acc += Math.min(now - last, 1000) / 1000
      last = now
      while (acc >= physics.tick_s) {
        acc -= physics.tick_s
        if (live.current.paused) continue
        const w = world.current
        for (const [at, until] of forcedUntil.current) {
          if (w.time > until || w.car.at > at + 5) {
            forced.current.delete(at)
            forcedUntil.current.delete(at)
          }
        }
        step(w, physics, net, live.current.ablation, forced.current)
        braking.current = w.action === 2 ? braking.current + 1 : 0
        // Committed: braking for 0.8 s, not the first marginal tick of it; or standing still.
        const when = live.current.armed
        if ((when === 'brake' && braking.current >= 8)
          || (when === 'stop' && braking.current >= 8 && w.car.speed < 0.3)) {
          live.current = { ...live.current, paused: true, armed: null }
          setPaused(true)
          setArmed(null)
        }
      }
    }, physics.tick_s * 1000)
    return () => window.clearInterval(id)
  }, [net, physics])

  // Drawing: every frame the browser gives us.
  useEffect(() => {
    let raf = 0
    const loop = () => {
      draw(canvas.current, world.current, physics, forced.current)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [physics])

  // Share the current moment with the trace device, and refresh the side panel.
  useEffect(() => {
    const id = window.setInterval(() => {
      const w = world.current
      // The inputs the car last decided on, so both devices show the same decision.
      const x = w.seen ?? features(w, physics, forced.current)
      send({ type: 'scene', scenario: 'driving', x, reference: reference(x),
        title: `The car at ${Math.round(w.car.speed * 3.6)} km/h`,
        context: describe(w, physics, forced.current), at: Date.now() })
      setFrame((f) => f + 1)
    }, 250)
    return () => window.clearInterval(id)
  }, [physics, send])

  const w = world.current
  const act = ACTIONS[w.action]

  const redAhead = () => {
    const l = nextLight(w, physics)
    if (!l) return
    forced.current.set(l.at, 'red')
    forcedUntil.current.set(l.at, w.time + 20)
  }
  const twoHazards = () => {
    const l = nextLight(w, physics)
    if (!l) return
    forced.current.set(l.at, 'red')
    forcedUntil.current.set(l.at, w.time + 30)
    setArmed('stop')
    setPaused(false)
    w.pedestrians.push({ id: w.nextId++, crosswalk: l.at + 6, x: 1, speed: 0.35, wait: 0 })
  }
  const restart = () => {
    world.current = newWorld(Math.floor(Math.random() * 1000))
    forced.current.clear()
    forcedUntil.current.clear()
  }

  return (
    <div className="sim">
      <div className="stage">
        <canvas ref={canvas} aria-label="The road from above. The car drives up the screen." />
      </div>
      <aside className="side">
        <section>
          <h3>The car's network decides</h3>
          <div className="decision">
            <span className={`word ${act}`}>{cap(act)}</span>
            <span className="muted">{Math.round(w.probs[w.action] * 100)}% sure</span>
          </div>
          <ul className="facts">{describe(w, physics, forced.current).map((f) => <li key={f}>{f}</li>)}</ul>
        </section>
        {off.length > 0 && (
          <p className="banner" role="status">
            {off.length} {off.length === 1 ? 'neuron is' : 'neurons are'} switched off from the
            trace device. The car is driving on what is left.
          </p>
        )}
        <section>
          <h3>Set up a moment</h3>
          <div className="controls">
            <button type="button" onClick={() => stepOut(w, physics)}>Someone steps out</button>
            <button type="button" onClick={redAhead}>Next light turns red</button>
            <button type="button" onClick={() => cutIn(w)}>A car cuts in</button>
            <button type="button" onClick={twoHazards}>Red light and a pedestrian</button>
          </div>
        </section>
        <section>
          <h3>Conditions</h3>
          <div className="controls">
            <button type="button" aria-pressed={w.rain} onClick={() => { w.rain = !w.rain }}>
              {w.rain ? 'Rain: on' : 'Rain: off'}</button>
            <button type="button" aria-pressed={w.night} onClick={() => { w.night = !w.night }}>
              {w.night ? 'Night: on' : 'Night: off'}</button>
            <button type="button" className="primary" onClick={() => setPaused((p) => !p)}>
              {paused ? 'Resume' : 'Pause on this moment'}</button>
            <button type="button" aria-pressed={armed !== null}
              onClick={() => setArmed((a) => (a ? null : 'brake'))}>
              {armed === 'stop' ? 'Will pause when it stops' : armed ? 'Will pause at the next brake'
                : 'Pause at the next brake'}</button>
            <button type="button" className="quiet" onClick={restart}>Start a new drive</button>
          </div>
        </section>
        <section>
          <h3>What happened on the road</h3>
          {w.incidents.length === 0 ? <p className="muted">No incidents, {Math.round(w.car.at)} m
            driven.</p> : (
            <ul className="incidents">
              {[...w.incidents].reverse().slice(0, 6).map((i) => (
                <li key={`${i.kind}-${i.time}`}><span className="bad">{INCIDENT_WORDS[i.kind]}</span>
                  {' '}at {Math.round(i.time)} s</li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  )
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1)

const COLOURS: Record<Colour, string> = { red: '#d33a4c', yellow: '#e0b43a', green: '#3fa36b' }

function draw(c: HTMLCanvasElement | null, w: World, p: Physics, forced: Map<number, Colour>) {
  if (!c) return
  const dpr = window.devicePixelRatio || 1
  const W = c.clientWidth, H = c.clientHeight
  if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
    c.width = Math.round(W * dpr)
    c.height = Math.round(H * dpr)
  }
  const g = c.getContext('2d')
  if (!g) return
  g.setTransform(dpr, 0, 0, dpr, 0, 0)

  const behind = 25
  const ppm = H / (p.view_m + behind) // pixels per metre along the road
  const carY = H - behind * ppm
  const y = (at: number) => carY - (at - w.car.at) * ppm
  const roadW = Math.min(W * 0.46, 300)
  const left = (W - roadW) / 2
  const lane = roadW / 2
  const xAcross = (m: number) => left + (m / ROAD_WIDTH) * roadW

  // ground and road
  g.fillStyle = w.night ? '#1d2a22' : '#7f9a7c'
  g.fillRect(0, 0, W, H)
  g.fillStyle = w.night ? '#24272f' : '#3b4150'
  g.fillRect(left, 0, roadW, H)
  g.fillStyle = '#c9ccd3'
  g.fillRect(left - 3, 0, 3, H)
  g.fillRect(left + roadW, 0, 3, H)
  g.strokeStyle = '#e8e3c4'
  g.lineWidth = 2
  g.setLineDash([18, 16])
  g.lineDashOffset = (w.car.at * ppm) % 34
  g.beginPath()
  g.moveTo(left + lane, 0)
  g.lineTo(left + lane, H)
  g.stroke()
  g.setLineDash([])

  // crosswalks
  for (const cw of w.crosswalks) {
    const cy = y(cw)
    if (cy < -30 || cy > H + 30) continue
    g.fillStyle = '#e9ecef'
    for (let i = 0; i < 9; i++) g.fillRect(left + 4 + i * (roadW / 9), cy - 3 * ppm, roadW / 18, 3 * ppm)
  }

  // traffic lights and stop lines
  for (const l of w.lights) {
    const ly = y(l.at)
    if (ly < -40 || ly > H + 40) continue
    const colour = colourAt(l, w.time, forced)
    g.fillStyle = '#f4f4f4'
    g.fillRect(left + lane, ly, lane, 3)
    const bx = left + roadW + 14
    g.fillStyle = '#15171c'
    g.fillRect(bx, ly - 40, 18, 46)
    ;(['red', 'yellow', 'green'] as Colour[]).forEach((col, k) => {
      g.beginPath()
      g.arc(bx + 9, ly - 32 + k * 14, 5, 0, Math.PI * 2)
      g.fillStyle = col === colour ? COLOURS[col] : '#3a3d45'
      g.fill()
    })
    if (forced.has(l.at)) {
      g.fillStyle = '#f6f8f3'
      g.font = '600 11px Public Sans, sans-serif'
      g.fillText('held red', bx + 24, ly - 20)
    }
  }

  // pedestrians
  for (const ped of w.pedestrians) {
    const py = y(ped.crosswalk) - 1.5 * ppm
    if (py < -20 || py > H + 20) continue
    const px = ped.wait > 0 ? left - 10 : xAcross(ped.x)
    g.beginPath()
    g.arc(px, py, 7, 0, Math.PI * 2)
    g.fillStyle = '#f2c14e'
    g.fill()
    g.lineWidth = 2
    g.strokeStyle = '#15171c'
    g.stroke()
  }

  // the car ahead
  // Cars are drawn longer than true scale, so they read as cars at any screen size.
  const carLen = Math.max(4.6 * ppm, lane * 1.5)
  if (w.lead) drawCar(g, left + lane + lane / 2, y(w.lead.at) + carLen / 2, lane * 0.5, carLen,
    '#8a93a6', false, false)

  // our car
  const braking = w.action === 2
  if (w.night) {
    const grad = g.createLinearGradient(0, carY, 0, carY - 60 * ppm)
    grad.addColorStop(0, 'rgba(255,240,190,0.35)')
    grad.addColorStop(1, 'rgba(255,240,190,0)')
    g.fillStyle = grad
    g.beginPath()
    g.moveTo(left + lane + lane * 0.3, carY - 2 * ppm)
    g.lineTo(left + lane - 6, carY - 60 * ppm)
    g.lineTo(left + roadW + 6, carY - 60 * ppm)
    g.lineTo(left + lane + lane * 0.7, carY - 2 * ppm)
    g.fill()
  }
  drawCar(g, left + lane + lane / 2, carY + carLen / 2, lane * 0.52, carLen, '#f6f8f3', braking,
    true)

  if (w.rain) {
    g.strokeStyle = 'rgba(210,220,235,0.35)'
    g.lineWidth = 1
    const t = w.time * 600
    for (let i = 0; i < 120; i++) {
      const rx = (i * 97 + t * 0.3) % W
      const ry = (i * 53 + t) % H
      g.beginPath()
      g.moveTo(rx, ry)
      g.lineTo(rx - 4, ry + 12)
      g.stroke()
    }
  }

  const recent = w.incidents.filter((i) => w.time - i.time < 2.5)
  if (recent.length) {
    g.fillStyle = 'rgba(163,35,58,0.85)'
    g.fillRect(0, 0, W, 44)
    g.fillStyle = '#fff'
    g.font = '700 18px Public Sans, sans-serif'
    g.fillText(INCIDENT_WORDS[recent[recent.length - 1].kind], 16, 29)
  }
}

function drawCar(g: CanvasRenderingContext2D, cx: number, cy: number, w: number, h: number,
  body: string, braking: boolean, ours: boolean) {
  g.fillStyle = body
  g.strokeStyle = '#15171c'
  g.lineWidth = 2
  g.beginPath()
  g.roundRect(cx - w / 2, cy - h / 2, w, h, 5)
  g.fill()
  g.stroke()
  g.fillStyle = ours ? '#1e2942' : '#5b6477'
  g.fillRect(cx - w / 2 + 4, cy - h / 2 + h * 0.22, w - 8, h * 0.2)
  g.fillStyle = braking ? '#ff3b4f' : '#7a2a33'
  g.fillRect(cx - w / 2 + 2, cy + h / 2 - 4, 8, 3)
  g.fillRect(cx + w / 2 - 10, cy + h / 2 - 4, 8, 3)
}
