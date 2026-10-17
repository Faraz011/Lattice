import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { type InterpSummary, InterpPanel, InterpView } from '../components/InterpPanel'

const summary: InterpSummary = {
  slug: 'tool-choice-case_1-qwen3-0.6b', model: 'qwen3-0.6b',
  prompt: 'Which tool should the investigator call first?\nAnswer:',
  recorded_tool: 'graph_match_pattern', chosen_letter: 'C',
  options: [
    { letter: 'A', tool: 'graph_neighbors', probability: 0.201 },
    { letter: 'C', tool: 'graph_match_pattern', probability: 0.612 },
    { letter: 'D', tool: 'algo_pagerank', probability: null },
  ],
  features: [{ node_id: '12_4400_3', layer: '12', token: ' chain', label: 'laundering shapes',
    effect: 0.5, influence: 0.41 }],
  error_share: 0.3, nodes: 6, links: 5,
}

afterEach(() => vi.unstubAllGlobals())

describe('InterpView', () => {
  it('shows the question, the option probabilities and what drives the chosen answer', () => {
    render(<InterpView summary={summary} />)

    expect(screen.getByText(/explains this\s+open model's answer, not the production/))
      .toBeInTheDocument()
    const chosen = screen.getByText("the investigator's choice").closest('li')!
    expect(chosen).toHaveTextContent('graph match pattern')
    expect(chosen).toHaveTextContent('p = 0.612')
    expect(screen.getByText('not in the graph')).toBeInTheDocument()
    const row = screen.getAllByRole('row')[1]
    expect(row).toHaveTextContent('+0.500')
    expect(row).toHaveTextContent('chain')
    expect(row).toHaveTextContent('laundering shapes')
    expect(screen.getByText(/30% of the\s+answer's direct input comes from reconstruction/))
      .toBeInTheDocument()
  })
})

describe('InterpPanel', () => {
  it('explains how to produce a graph when none has been exported', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })))

    render(<InterpPanel />)

    expect(await screen.findByText(/No attribution graph has been produced yet/))
      .toBeInTheDocument()
  })

  it('loads an exported summary', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(summary))))

    render(<InterpPanel />)

    expect(await screen.findByText("the investigator's choice")).toBeInTheDocument()
  })
})
