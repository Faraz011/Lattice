import { useEffect, useState } from 'react'

import { loadEpisode, type Episode } from '../sim/aml'
import { loadNet, type Net } from './net'

export interface Models {
  driving: Net
  aml: Net & { reference: number[] }
  episode: Episode
}

// Both networks and the bank episode, loaded once per page.
export function useModels(): { models: Models | null; error: string | null } {
  const [models, setModels] = useState<Models | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    Promise.all([loadNet('driving'), loadNet('aml'), loadEpisode()])
      .then(([driving, aml, episode]) => {
        if (live) setModels({ driving, aml: aml as Models['aml'], episode })
      })
      .catch((e: Error) => live && setError(e.message))
    return () => { live = false }
  }, [])
  return { models, error }
}
