// The link between the two devices: a room on the relay (src/lattice/lens/relay.py), joined by
// code. Tabs in one browser also reach each other directly, so the demo works on one machine
// without the relay.
import { useEffect, useMemo, useRef, useState } from 'react'

export type Scenario = 'driving' | 'aml'

export interface SceneMessage {
  type: 'scene'
  scenario: Scenario
  x: number[]
  reference: number[]
  title: string // what is being decided, e.g. "The car, 42 km/h" or "acct_9f2c, Mia Brooks"
  context: string[] // plain facts about the moment, shown above the trace
  at: number
}

export interface AblateMessage {
  type: 'ablate'
  scenario: Scenario
  nodes: string[]
}

export interface ScenarioMessage {
  type: 'scenario'
  scenario: Scenario
}

// Sent on connect and every few seconds, so each device knows the other is there.
export interface HelloMessage {
  type: 'hello'
  role: 'sim' | 'trace'
}

export type Message = SceneMessage | AblateMessage | ScenarioMessage | HelloMessage

export type LinkStatus = 'connecting' | 'paired' | 'alone' | 'offline'

interface Envelope { from: string; body: Message }

const ME = Math.random().toString(36).slice(2, 10)

export function newRoomCode(): string {
  const words = ['river', 'cedar', 'amber', 'harbor', 'maple', 'orbit', 'delta', 'summit']
  return `${words[Math.floor(Math.random() * words.length)]}-${Math.floor(100 + Math.random() * 900)}`
}

function socketUrl(room: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/${encodeURIComponent(room)}`
}

// Join `room`; `onMessage` gets every message from the other devices.
export function useLink(room: string, role: 'sim' | 'trace', onMessage: (m: Message) => void) {
  const [status, setStatus] = useState<LinkStatus>('connecting')
  const [peers, setPeers] = useState(0)
  const handler = useRef(onMessage)
  useEffect(() => { handler.current = onMessage }, [onMessage])
  const socket = useRef<WebSocket | null>(null)
  const channel = useRef<BroadcastChannel | null>(null)
  const seenPeers = useRef(new Map<string, number>())

  useEffect(() => {
    let closed = false
    let retry = 500
    let timer: number | undefined
    const receive = (env: Envelope) => {
      if (!env || env.from === ME || !env.body) return
      seenPeers.current.set(env.from, Date.now())
      setPeers(seenPeers.current.size)
      if (env.body.type !== 'hello') handler.current(env.body)
    }

    const bc = 'BroadcastChannel' in window ? new BroadcastChannel(`lens:${room}`) : null
    if (bc) bc.onmessage = (e) => receive(e.data as Envelope)
    channel.current = bc

    const connect = () => {
      if (closed) return
      let ws: WebSocket
      try {
        ws = new WebSocket(socketUrl(room))
      } catch {
        setStatus('offline')
        return
      }
      socket.current = ws
      ws.onopen = () => { retry = 500; setStatus('alone') }
      ws.onmessage = (e) => {
        try { receive(JSON.parse(e.data as string) as Envelope) } catch { /* not ours */ }
      }
      ws.onclose = () => {
        socket.current = null
        if (closed) return
        setStatus('offline')
        timer = window.setTimeout(connect, retry)
        retry = Math.min(retry * 2, 8000)
      }
    }
    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      socket.current?.close()
      bc?.close()
    }
  }, [room])

  const send = useMemo(() => (body: Message) => {
    // The relay reads `type` to keep the latest of each kind for devices that join later.
    const env = { type: body.type, from: ME, body }
    const ws = socket.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(env))
    channel.current?.postMessage(env)
  }, [])

  // Say hello now and every 4 s; a device unheard from for 12 s no longer counts as paired.
  useEffect(() => {
    const beat = () => {
      send({ type: 'hello', role })
      const now = Date.now()
      for (const [id, at] of seenPeers.current) if (now - at > 12_000) seenPeers.current.delete(id)
      setPeers(seenPeers.current.size)
    }
    beat()
    const id = window.setInterval(beat, 4000)
    return () => window.clearInterval(id)
  }, [send, role, status])

  useEffect(() => {
    if (status === 'offline' || status === 'connecting') return
    setStatus(peers > 0 ? 'paired' : 'alone')
  }, [peers, status])

  return { status, peers, send }
}
