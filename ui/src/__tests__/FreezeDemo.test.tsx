import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ExplanationSize } from '../components/ExplanationSize'
import { FreezeWhatIf, freezeVerdict } from '../components/FreezeWhatIf'
import { graphElements } from '../components/GraphView'
import { ResearchPanel } from '../components/ResearchPanel'
import { RoutesPanel } from '../components/RoutesPanel'
import type { FreezeWhatIf as WhatIf } from '../types'
import { evidence, report } from './fixtures'

const holds: WhatIf = {
  account_id: 'acct_two', role: 'mule', removed_edges: ['tx_a1', 'tx_b2'], score_before: 1,
  score_after: 0.67, still_flagged: true, typology_after: 'rapid_layering',
  backup_edges: ['tx_c3', 'tx_noise'],
}
const falls: WhatIf = { ...holds, account_id: 'acct_three', score_after: 0.2,
  still_flagged: false, typology_after: null, backup_edges: [] }

afterEach(() => vi.unstubAllGlobals())

describe('FreezeWhatIf', () => {
  it('says the case holds through a backup route, or falls, for the chosen account', async () => {
    const onSelect = vi.fn()
    const { rerender } = render(<FreezeWhatIf whatifs={[holds, falls]} threshold={0.6}
      active={null} onSelect={onSelect} onFocus={() => {}} />)

    expect(screen.getByText(/1 of 2 would stop it on their own/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Freeze acct_two, mule' }))
    expect(onSelect).toHaveBeenCalledWith('acct_two')

    rerender(<FreezeWhatIf whatifs={[holds, falls]} threshold={0.6} active="acct_two"
      onSelect={onSelect} onFocus={() => {}} />)
    expect(screen.getByRole('status')).toHaveTextContent(
      'The case still flags at 0.67. Another route of 2 transfers')
    expect(screen.getByRole('button', { name: 'Freeze acct_two, mule' }))
      .toHaveAttribute('aria-pressed', 'true')
  })

  it('names an essential account', () => {
    expect(freezeVerdict(falls, 0.6)).toMatch(/no longer flags.*falls from 1.00 to 0.20.*essential/)
  })
})

describe('ExplanationSize', () => {
  const curve = { ranked_edges: ['tx_a1', 'tx_b2', 'tx_c3'], scores: [0.2, 0.67, 0.82],
    sufficient_at: 2 }

  it('starts at the smallest flagging explanation and reports what each size covers', async () => {
    const onSize = vi.fn()
    render(<ExplanationSize curve={curve} fullScore={0.82} threshold={0.6} size={null}
      onSize={onSize} />)

    expect(screen.getByText('Strongest 2 transfers')).toBeInTheDocument()
    expect(screen.getByText(/score/).textContent).toMatch(/0.67 of the full 0.82 \(82%\)/)
    expect(screen.getByText(/smallest explanation that flags it has 2 transfers/))
      .toBeInTheDocument()
  })

  it('says when a size is below the threshold', () => {
    render(<ExplanationSize curve={curve} fullScore={0.82} threshold={0.6} size={1}
      onSize={() => {}} />)

    expect(screen.getByText(/below the 0.60 threshold/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back to the minimal circuit' }))
      .toBeInTheDocument()
  })
})

describe('RoutesPanel', () => {
  it('lists each route with roles and says how they relate', () => {
    render(<RoutesPanel onFocus={() => {}} relation="parallel: each is a backup"
      roles={{ acct_seed: 'originator', acct_two: 'mule', acct_four: 'collector' }}
      routes={[
        { edges: ['tx_a1'], path: ['tx_a1', 'tx_b2'], accounts: ['acct_seed', 'acct_two'],
          score: 0.67 },
        { edges: ['tx_c3'], path: ['tx_c3'], accounts: ['acct_two', 'acct_four'], score: 0.7 },
      ]} />)

    expect(screen.getByRole('heading', { name: '2 independent routes prove this case' }))
      .toBeInTheDocument()
    expect(screen.getByText('Route 2, a backup')).toBeInTheDocument()
    expect(screen.getByText(/The routes are parallel/)).toBeInTheDocument()
    expect(screen.getAllByText('originator')).toHaveLength(1)
  })
})

describe('graphElements for the freeze demo', () => {
  it('draws the backup route dashed and numbered B1, B2 and marks the frozen account', () => {
    const elements = graphElements(evidence, report, { backup: ['tx_c3', 'tx_noise'],
      frozen: 'acct_two', roles: { acct_two: 'mule' } })
    const byId = (id: string) => elements.find((e) => e.data.id === id)!

    expect(byId('tx_c3').classes).toContain('backup')
    expect(String(byId('tx_c3').data.label)).toMatch(/^B\d\. /)
    expect(byId('acct_two').classes).toContain('frozen')
    expect(byId('acct_two').data.label).toBe('acct_two, mule (frozen)')
  })

  it('draws a chosen explanation size as the proof', () => {
    const elements = graphElements(evidence, report, { proof: ['tx_c3'] })
    const byId = (id: string) => elements.find((e) => e.data.id === id)!

    expect(byId('tx_c3').classes).toContain('circuit')
    expect(byId('tx_a1').classes).not.toContain('circuit')
  })
})

describe('ResearchPanel', () => {
  it('explains how to add the research results when none are present', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })))

    render(<ResearchPanel />)

    expect(await screen.findByText(/Results on GPT-2 go here/)).toBeInTheDocument()
  })

  it('shows the results when present', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      title: 'Same method on GPT-2', summary: 's', model: 'GPT-2 small', source: 'notebook x',
      rows: [{ measure: 'KL to the full model', ours: '0.55', baseline: '0.50',
        baseline_name: 'Edge Pruning' }],
    }))))

    render(<ResearchPanel />)

    expect(await screen.findByText('KL to the full model')).toBeInTheDocument()
    expect(screen.getByText('(Edge Pruning)')).toBeInTheDocument()
  })
})
