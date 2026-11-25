// Device 1: the world. A switch picks the scenario; the trace device follows it.
import { useCallback, useEffect, useState } from 'react'

import { useLink, type Message, type Scenario } from '../link'
import { useModels } from '../model/useModels'
import { BankStage } from './BankStage'
import { DrivingStage } from './DrivingStage'
import { TopBar } from '../TopBar'

export function SimScreen({ room }: { room: string }) {
  const { models, error } = useModels()
  const [scenario, setScenario] = useState<Scenario>('driving')
  const [off, setOff] = useState<Record<Scenario, string[]>>({ driving: [], aml: [] })

  const onMessage = useCallback((m: Message) => {
    if (m.type === 'ablate') setOff((o) => ({ ...o, [m.scenario]: m.nodes }))
  }, [])
  const link = useLink(room, 'sim', onMessage)
  const { send } = link

  // Tell the trace device which scenario is on, now and whenever it (re)connects.
  useEffect(() => { send({ type: 'scenario', scenario }) }, [scenario, send, link.status])

  return (
    <>
      <TopBar room={room} link={link} role="Simulation">
        <div className="switch" role="group" aria-label="Scenario">
          <button type="button" aria-pressed={scenario === 'driving'}
            onClick={() => setScenario('driving')}>Self-driving car</button>
          <button type="button" aria-pressed={scenario === 'aml'}
            onClick={() => setScenario('aml')}>Bank: money laundering</button>
        </div>
      </TopBar>
      {error && <p className="banner" role="alert">{error}</p>}
      {!models && !error && <p className="waiting">Loading the networks.</p>}
      {models && scenario === 'driving' && (
        <DrivingStage net={models.driving} route={models.london} off={off.driving} send={send} />
      )}
      {models && scenario === 'aml' && (
        <BankStage net={models.aml} episode={models.episode} off={off.aml} send={send} />
      )}
    </>
  )
}
