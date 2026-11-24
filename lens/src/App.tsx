// Three screens, routed by the URL hash so the relay can serve one page:
//   #/                   choose what this device does, and the room both devices join
//   #/sim/<room>         device 1: the simulation, self-driving car or bank
//   #/trace/<room>       device 2: inside the network that makes the decision
import { useEffect, useState } from 'react'

import { newRoomCode } from './link'
import { SimScreen } from './sim/SimScreen'
import { TraceScreen } from './trace/TraceScreen'

function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const on = () => setRoute(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export function App() {
  const [page, room] = useRoute()
  if (page === 'sim' && room) return <SimScreen room={room} />
  if (page === 'trace' && room) return <TraceScreen room={room} />
  return <Home />
}

function Home() {
  const [room, setRoom] = useState(newRoomCode)
  const valid = /^[A-Za-z0-9-]{3,32}$/.test(room)
  const go = (page: string) => { window.location.hash = `#/${page}/${room}` }
  return (
    <main className="home">
      <h1>Watch a decision happen, and see inside it.</h1>
      <p className="lede">
        One device runs the world: a self-driving car on a city road, or two weeks of a small
        bank. The other shows the neural network deciding what to do, neuron by neuron: the
        circuit behind each decision, and the backup route that would take over if that circuit
        failed.
      </p>
      <div className="room-field">
        <label htmlFor="room">Room code for both devices</label>
        <input id="room" value={room} onChange={(e) => setRoom(e.target.value.trim())}
          aria-invalid={!valid} />
        <button type="button" className="quiet" onClick={() => setRoom(newRoomCode())}>
          New code</button>
      </div>
      <div className="roles">
        <section className="role">
          <h2>Run the simulation</h2>
          <p className="muted">The car or the bank, with controls to set up a moment worth
            explaining.</p>
          <button type="button" className="primary" disabled={!valid} onClick={() => go('sim')}>
            Open the simulation</button>
        </section>
        <section className="role">
          <h2>Look inside the model</h2>
          <p className="muted">The live circuit for whatever the simulation is deciding. Switch
            a neuron off here and watch the car or the bank react.</p>
          <button type="button" className="primary" disabled={!valid} onClick={() => go('trace')}>
            Open the trace</button>
        </section>
      </div>
      <p className="muted" style={{ marginTop: '2rem' }}>
        On the other device, open this page and enter the same code, or go straight to{' '}
        <code>{window.location.host}/#/trace/{room}</code>.
      </p>
    </main>
  )
}
