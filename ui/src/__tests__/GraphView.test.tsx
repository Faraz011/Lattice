import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { circuitOrder, graphElements } from '../components/GraphView'
import { Inspector } from '../components/Inspector'
import { evidence, report } from './fixtures'

const edge = (elements: ReturnType<typeof graphElements>, id: string) =>
  elements.find((e) => e.data.id === id)!

describe('graphElements', () => {
  it('draws every ledgered edge plainly while the case is still being investigated', () => {
    const elements = graphElements(evidence, null, { seed: 'acct_seed' })

    expect(elements.filter((e) => e.group === 'edges')).toHaveLength(4)
    expect(edge(elements, 'tx_noise').classes).toBe('transfer')
    expect(edge(elements, 'acct_seed').classes).toContain('seed')
  })

  it('marks circuit edges with numbers in time order, not by colour alone', () => {
    const elements = graphElements(evidence, report)

    expect(edge(elements, 'tx_a1').classes).toContain('circuit')
    expect(edge(elements, 'tx_a1').data.label).toBe('1. $9,000')
    expect(edge(elements, 'tx_b2').data.label).toBe('2. $8,600')
    expect(circuitOrder(report).get('tx_b2')).toBe(2)
  })

  it('keeps supporting evidence in ink and fades edges the detectors did not use', () => {
    const elements = graphElements(evidence, report)

    expect(edge(elements, 'tx_c3').classes).toContain('supporting')
    expect(edge(elements, 'tx_noise').classes).toContain('context')
    expect(edge(elements, 'tx_noise').data.label).toBe('')
  })

  it('marks the edges a counterfactual removes', () => {
    const elements = graphElements(evidence, report, { removed: new Set(['tx_a1']) })

    expect(edge(elements, 'tx_a1').classes).toContain('removed')
    expect(edge(elements, 'tx_b2').classes).not.toContain('removed')
  })

  it('draws edges the report names even when the evidence view does not have them', () => {
    const elements = graphElements({ ...evidence, edges: [] }, report)

    expect(edge(elements, 'tx_b2')).toBeDefined()
    expect(edge(elements, 'acct_three')).toBeDefined()
  })

  it('labels mixers by kind and draws devices as devices', () => {
    const withDevice = {
      ...evidence,
      nodes: [...evidence.nodes, { id: 'dev_9', kind: 'device' as const }],
      edges: [...evidence.edges, { id: 'used_device:acct_two:dev_9', kind: 'device_link' as const,
        src: 'acct_two', dst: 'dev_9', sources: ['led_first'] }],
    }

    const elements = graphElements(withDevice, null)

    expect(edge(elements, 'acct_four').data.label).toContain('(mixer)')
    expect(edge(elements, 'dev_9').classes).toContain('device')
    expect(edge(elements, 'used_device:acct_two:dev_9').classes).toBe('device-link')
  })
})

describe('Inspector', () => {
  it('shows the ledger entries that returned a clicked edge', () => {
    render(<Inspector id="tx_b2" evidence={evidence} report={report} onClose={() => {}} />)

    expect(screen.getByText('graph_neighbors')).toBeInTheDocument()
    expect(screen.getByText('graph_match_pattern')).toBeInTheDocument()
    expect(screen.getByText('led_second')).toBeInTheDocument()
    expect(screen.getByText('pattern: peeling_chain')).toBeInTheDocument()
    expect(screen.getByText(/part of the circuit/)).toBeInTheDocument()
  })

  it('closes', async () => {
    const onClose = vi.fn()
    render(<Inspector id="tx_a1" evidence={evidence} report={report} onClose={onClose} />)

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))

    expect(onClose).toHaveBeenCalled()
  })
})
