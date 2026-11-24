import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type Approver } from '../api'
import { ApprovalPanel, useApprover } from '../components/ApprovalPanel'
import type { Action } from '../types'
import { freeze } from './fixtures'

function Harness({ action, onApprove = async () => undefined,
  onReject = async () => undefined, readOnly = false }: {
  action: Action
  onApprove?: () => Promise<unknown>
  onReject?: (reason: string) => Promise<unknown>
  readOnly?: boolean
}) {
  const [approver, setApprover] = useState<Approver>({ token: '', name: '' })
  return <ApprovalPanel action={action} approver={approver} onApproverChange={setApprover}
    onApprove={onApprove} onReject={onReject} readOnly={readOnly} />
}

const approveButton = () => screen.getByRole('button', { name: 'Freeze account' })

async function enterToken() {
  await userEvent.type(screen.getByLabelText('Approver token'), 'secret')
}

describe('ApprovalPanel', () => {
  it('shows the blast radius and needs a token and a review before approving', async () => {
    const onApprove = vi.fn(async () => undefined)
    render(<Harness action={freeze} onApprove={onApprove} />)

    expect(screen.getByText('14 accounts')).toBeInTheDocument()
    expect(screen.getByText('9 customers')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()

    await enterToken()
    expect(approveButton()).toBeDisabled()

    await userEvent.click(screen.getByLabelText('I have reviewed the blast radius'))
    await userEvent.click(approveButton())
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it('cannot approve a tier 2-3 action before its blast radius exists', async () => {
    render(<Harness action={{ ...freeze, blast_radius: null }} />)
    await enterToken()

    expect(screen.getByText('Waiting for the blast radius before approval.')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
  })

  it('shows a rejected token inline', async () => {
    const onApprove = vi.fn(async () => { throw new ApiError(401, 'bad token') })
    render(<Harness action={freeze} onApprove={onApprove} />)
    await enterToken()
    await userEvent.click(screen.getByLabelText('I have reviewed the blast radius'))

    await userEvent.click(approveButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That approver token was not accepted')
  })

  it('rejects with a reason', async () => {
    const onReject = vi.fn(async () => undefined)
    render(<Harness action={freeze} onReject={onReject} />)
    await enterToken()

    await userEvent.type(screen.getByLabelText('Reason for rejecting'), 'customer explained it')
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))

    expect(onReject).toHaveBeenCalledWith('customer explained it')
  })

  it.each([
    [{ status: 'approved', approved_by: 'sam' }, 'Approved by sam. Executing.'],
    [{ status: 'executed', outcome: 'account acct_seed frozen (simulated)' },
      'Done: account acct_seed frozen (simulated).'],
    [{ status: 'rejected', rejected_by: 'sam', rejection_reason: 'false positive' },
      'Rejected by sam: false positive.'],
    [{ status: 'refused', refusal_reason: 'not approved' },
      'The executor refused this action: not approved.'],
  ] as const)('shows the %o state', (change, text) => {
    render(<Harness action={{ ...freeze, ...change } as Action} />)

    expect(screen.getByRole('status')).toHaveTextContent(text)
    expect(screen.queryByRole('button', { name: 'Freeze account' })).not.toBeInTheDocument()
  })

  it('offers no decision in a replay', () => {
    render(<Harness action={freeze} readOnly />)

    expect(screen.getByRole('status')).toHaveTextContent('Decisions are turned off')
    expect(screen.queryByLabelText('Approver token')).not.toBeInTheDocument()
  })

  it('keeps the token in this tab only, never in local storage', async () => {
    const { unmount } = render(<ApprovalPanelWithStorage />)
    await enterToken()
    unmount()

    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.getItem('lattice.approver')).toContain('secret')
  })
})


function ApprovalPanelWithStorage() {
  const [approver, setApprover] = useApprover()
  return <ApprovalPanel action={freeze} approver={approver} onApproverChange={setApprover}
    onApprove={async () => undefined} onReject={async () => undefined} />
}
