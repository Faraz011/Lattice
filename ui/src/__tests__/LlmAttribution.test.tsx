import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { LlmAttribution } from '../components/LlmAttribution'
import type { LLMAttribution } from '../types'

const complete: LLMAttribution = {
  status: 'complete', samples: 16, budget: 16, full_probability: 0.85, agreement: 1,
  note: null,
  sources: [
    { result_id: 'led_pattern', tool: 'graph_match_pattern', weight: 0.68,
      circuit_edges: ['tx_a1', 'tx_b2'] },
    { result_id: 'led_node', tool: 'graph_get_node', weight: 0, circuit_edges: [] },
  ],
}

describe('LlmAttribution', () => {
  it('ranks the tool results by weight and marks the ones holding the circuit', async () => {
    const onFocus = vi.fn()
    render(<LlmAttribution attribution={complete} onFocus={onFocus} />)

    expect(screen.getByText(/left out at random 16 times/)).toHaveTextContent('85%')
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('+0.68')
    expect(items[0]).toHaveTextContent('graph match pattern')
    expect(screen.getByText(/Of the 1 result that holds the\s+scorer's circuit, 1 is among/))
      .toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'holds 2 circuit edges' }))
    expect(onFocus).toHaveBeenCalledWith('tx_a1')
  })

  it('says when too few samples ran instead of showing weights', () => {
    render(<LlmAttribution onFocus={() => {}} attribution={{ ...complete,
      status: 'insufficient', sources: [], agreement: null, samples: 3,
      note: 'only 3 of 16 samples ran before the model budget ran out' }} />)

    expect(screen.getByText(/only 3 of 16 samples ran/)).toBeInTheDocument()
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
  })
})
