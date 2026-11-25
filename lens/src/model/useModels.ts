import { useEffect, useState } from 'react'

import { loadEpisode, type Episode } from '../sim/aml'
import type { RouteMap } from '../sim/driving'
import { loadNet, type Net } from './net'

export interface Models {
  driving: Net
  aml: Net & { reference: number[] }
  episode: Episode
  london: RouteMap
}

// Both networks and the bank episode, loaded once per page.
export function useModels(): { models: Models | null; error: string | null } {
  const [models, setModels] = useState<Models | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    const london = fetch(`${import.meta.env.BASE_URL}maps/london.json`).then((r) => {
      if (!r.ok) throw new Error(`Could not load the London route (${r.status}).`)
      return r.json() as Promise<RouteMap>
    })
    Promise.all([loadNet('driving'), loadNet('aml'), loadEpisode(), london])
      .then(([driving, aml, episode, route]) => {
        if (live) setModels({ driving, aml: aml as Models['aml'], episode, london: route })
      })
      .catch((e: Error) => live && setError(e.message))
    return () => { live = false }
  }, [])
  return { models, error }
}
