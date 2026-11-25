// The self-driving car in central London. The car's network decides every 0.1 s; the presenter
// sets up hazards; the trace device gets the current moment four times a second.
import { useEffect, useMemo, useRef, useState } from 'react'

import type { Message } from '../link'
import type { Net } from '../model/net'
import { CityMap } from './CityMap'
import { FORCE_OPEN, ION_TOKEN, PhotoCity, TRY_PHOTO, type Camera } from './PhotoCity'
import { StreetCam } from './StreetCam'
import { STREET_KEY } from './streetview'
import {
  ACTIONS, cutIn, describe, features, nextLight, reference, rel, step, stepOut, worldFromMap,
  type Colour, type Physics, type RouteMap, type World,
} from './driving'

const INCIDENT_WORDS = {
  red_light: 'Ran a red light',
  pedestrian: 'Drove through a crosswalk with someone on it',
  collision: 'Hit the car ahead',
} as const

const CAMERA_NAMES: Record<Camera, string> = {
  front: 'FRONT CAMERA', rear: 'REAR CAMERA', chase: 'CHASE VIEW',
}

interface Props {
  net: Net
  route: RouteMap
  off: string[]
  send: (m: Message) => void
}

export function DrivingStage({ net, route, off, send }: Props) {
  const physics = net.physics as unknown as Physics
  const world = useRef<World>(worldFromMap(route, 1))
  const forced = useRef(new Map<number, Colour>())
  const forcedUntil = useRef(new Map<number, number>())
  const [paused, setPaused] = useState(false)
  // Photorealistic London when a Cesium ion token is configured; the open map otherwise.
  const [photo, setPhoto] = useState((Boolean(ION_TOKEN) || TRY_PHOTO) && !FORCE_OPEN)
  // A view that cannot load steps aside quietly for the next one; the reason goes to the
  // browser console for whoever is setting the demo up, never onto the stage.
  const [photoWhy, setPhotoWhy] = useState<string | null>(null) // why the 3D city fell back
  const fellBack = (view: string, why: string) => console.warn(`${view} unavailable, falling back:`, why)
  const [camera, setCamera] = useState<Camera>('front')
  // Google Street View for the car's own cameras, when a key is configured.
  const [street, setStreet] = useState(Boolean(STREET_KEY) && !FORCE_OPEN)
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
          if (w.time > until || rel(w, at) < -5) {
            forced.current.delete(at)
            forcedUntil.current.delete(at)
          }
        }
        step(w, physics, net, live.current.ablation, forced.current)
        w.tickAt = performance.now()
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
    // Someone on the junction's own crossing, or on a crossing just past the stop line.
    let cw = w.crosswalks.find((c) => rel(w, c) - rel(w, l.at) >= 0 && rel(w, c) - rel(w, l.at) < 25)
    if (cw === undefined) {
      cw = l.at + 6
      w.crosswalks = [...w.crosswalks, cw].sort((a, b) => a - b)
    }
    w.pedestrians.push({ id: w.nextId++, crosswalk: cw, x: 1, speed: 0.35, wait: 0 })
  }
  const restart = () => {
    world.current = worldFromMap(route, Math.floor(Math.random() * 1000))
    forced.current.clear()
    forcedUntil.current.clear()
  }

  return (
    <div className="sim">
      <div className="stage city">
        {street && camera !== 'chase'
          ? <StreetCam world={world} map={route} forced={forced} tick={physics.tick_s}
              physics={physics} rear={camera === 'rear'}
              onFail={(why) => { fellBack('Street View', why); setStreet(false) }} />
          : photo
          ? <PhotoCity world={world} map={route} forced={forced} tick={physics.tick_s}
              physics={physics} camera={camera}
              onFail={(why) => { fellBack('Photorealistic 3D city', why); setPhotoWhy(why); setPhoto(false) }} />
          : <CityMap world={world} map={route} forced={forced} tick={physics.tick_s}
              physics={physics} camera={camera} />}
        <span className="cam-label" aria-hidden="true">
          {CAMERA_NAMES[camera]} · {street && camera !== 'chase' ? 'STREET VIEW' : photo ? '3D CITY' : 'MAP'}
        </span>
        {!photo && Boolean(ION_TOKEN) && !FORCE_OPEN && (
          <button type="button" className="retry-3d" title={photoWhy ?? 'The 3D city is off'}
            onClick={() => { setPhotoWhy(null); setPhoto(true) }}>Load 3D city</button>
        )}
        <div className="cams" role="group" aria-label="Camera">
          {(['front', 'rear', 'chase'] as Camera[]).map((c) => (
            <button key={c} type="button" aria-pressed={camera === c} onClick={() => setCamera(c)}>
              {c === 'front' ? 'Front camera' : c === 'rear' ? 'Rear camera' : 'Chase view'}</button>
          ))}
        </div>
        <div className="hud" aria-hidden="true">
          <span className="speed">{Math.round(w.car.speed * 3.6)}<small>km/h</small></span>
          <span className={`act ${act}`}>{act}</span>
        </div>
        <p className="credit">{route.name}. {route.source}</p>
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
          {w.incidents.length === 0 ? <p className="muted">No incidents, {(w.odometer / 1000).toFixed(1)} km
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
