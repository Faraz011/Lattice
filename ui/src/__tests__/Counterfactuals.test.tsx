import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Counterfactuals } from '../components/Counterfactuals'
import { report } from './fixtures'

describe('Counterfactuals', () => {
  it('shows the precomputed score for each removal', () => {
    render(<Counterfactuals report={report} active={null} onToggle={() => {}} />)

    expect(screen.getByRole('button', { name: 'Without tx_a1' })).toHaveAttribute(
      'aria-pressed', 'false')
    expect(screen.getByText('0.82 falls to 0.41')).toBeInTheDocument()
  })

  it('toggles a removal on and off without rescoring', async () => {
    const onToggle = vi.fn()
    const { rerender } = render(
      <Counterfactuals report={report} active={null} onToggle={onToggle} />)

    await userEvent.click(screen.getByRole('button', { name: 'Without tx_a1' }))
    expect(onToggle).toHaveBeenLastCalledWith(0)

    rerender(<Counterfactuals report={report} active={0} onToggle={onToggle} />)
    expect(screen.getByRole('button', { name: 'Without tx_a1' })).toHaveAttribute(
      'aria-pressed', 'true')
    expect(screen.getByText(/nothing is rescored here/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Without tx_a1' }))
    expect(onToggle).toHaveBeenLastCalledWith(null)
  })

  it('says when no counterfactual exists within the bound', () => {
    const none = { ...report, counterfactuals: { counterfactuals: [],
      note: 'no counterfactual within bound' } }

    render(<Counterfactuals report={none} active={null} onToggle={() => {}} />)

    expect(screen.getByText(/No counterfactual within bound/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
