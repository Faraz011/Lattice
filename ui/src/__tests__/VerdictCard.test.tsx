import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Narrative } from '../components/Narrative'
import { VerdictCard } from '../components/VerdictCard'
import { report, verdict } from './fixtures'

describe('VerdictCard', () => {
  it('states the pattern, score and threshold of a flagged case', () => {
    render(<VerdictCard verdict={verdict} report={report} outcome="awaiting_approval" />)

    expect(screen.getByRole('heading', { name: 'Suspicious activity found' })).toBeInTheDocument()
    expect(screen.getByText('0.82')).toBeInTheDocument()
    expect(screen.getByText(/peeling chain, high risk/)).toBeInTheDocument()
    expect(screen.getByText(/flagging threshold 0.60/)).toBeInTheDocument()
    expect(screen.getByText(/The proof is 2 edges/)).toBeInTheDocument()
  })

  it('gives the reason a case was closed without action', () => {
    render(<VerdictCard verdict={{ ...verdict, suspicious: false, score: 0.31, risk: 'low' }}
      report={null} outcome="closed_no_action" reason="score 0.31 is below 0.60" />)

    expect(screen.getByRole('heading', { name: 'No suspicious pattern found' }))
      .toBeInTheDocument()
    expect(screen.getByText('Closed without action: score 0.31 is below 0.60.'))
      .toBeInTheDocument()
  })

  it('shows both verdicts side by side when a case needs review', () => {
    render(<VerdictCard
      verdict={{ ...verdict, investigator_typology: 'fan_out', needs_review: true,
        review_reason: 'the investigators and the scorer disagree' }}
      report={report} outcome="needs_review" />)

    expect(screen.getByText('Risk scorer').nextSibling).toHaveTextContent('peeling chain')
    expect(screen.getByText('Investigators').nextSibling).toHaveTextContent('fan out')
    expect(screen.getByText('the investigators and the scorer disagree')).toBeInTheDocument()
  })

  it('flags redundant evidence', () => {
    const redundant = { ...report, circuit: { ...report.circuit, redundant: true,
      comprehensive: false } }

    render(<VerdictCard verdict={verdict} report={redundant} outcome="awaiting_approval" />)

    expect(screen.getByText(/second, independent body of evidence/)).toBeInTheDocument()
  })

  it('counts dropped citations', () => {
    render(<VerdictCard verdict={{ ...verdict, rejected_citations: ['tx_fake'],
      unverified_ids: ['tx_gone', 'tx_gone2'] }} report={report} outcome="awaiting_approval" />)

    expect(screen.getByText(/1 citations were dropped/)).toHaveTextContent('2 no longer exist')
  })
})

describe('Narrative', () => {
  it('turns every ID into a button that focuses it on the graph', async () => {
    const onFocus = vi.fn()
    render(<Narrative onFocus={onFocus} narrative={{ source: 'model',
      text: 'Money left acct_seed through tx_a1.\n\nIt then moved on.' }} />)

    await userEvent.click(screen.getByRole('button', { name: 'tx_a1' }))

    expect(onFocus).toHaveBeenCalledWith('tx_a1')
    expect(screen.getByRole('button', { name: 'acct_seed' })).toBeInTheDocument()
    expect(screen.getByText('It then moved on.')).toBeInTheDocument()
  })

  it('says when the template wrote the text', () => {
    render(<Narrative onFocus={() => {}} narrative={{ source: 'template', text: 'x' }} />)

    expect(screen.getByText(/Written from a template/)).toBeInTheDocument()
  })
})
