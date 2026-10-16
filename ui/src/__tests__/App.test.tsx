import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import App from '../App'
import type { Alert } from '../types'

const alert: Alert = {
  id: 'alert_1', seed_account_id: 'acct_seed', reason: 'many outbound transfers in a short period',
  ts: '2026-09-01T10:00:00', case_id: null, case_status: null, recorded_case_id: null,
}

vi.mock('../api', async (original) => {
  const actual = await original<typeof import('../api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      alerts: vi.fn(async () => [alert]),
      investigate: vi.fn(async () => {
        throw new actual.ApiError(429, '5 investigations are already open (limit 5)')
      }),
    },
  }
})

describe('App', () => {
  it('keeps the alert list on screen when an investigation cannot start', async () => {
    render(<App />)

    await userEvent.click(await screen.findByRole('button', { name: 'Investigate' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The investigation could not start: 5 investigations are already open (limit 5).')
    expect(screen.getByText(alert.reason)).toBeInTheDocument()
    expect(screen.queryByText(/Alerts could not be loaded/)).not.toBeInTheDocument()
  })
})
