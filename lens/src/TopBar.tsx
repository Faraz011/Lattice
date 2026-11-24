import type { ReactNode } from 'react'

import type { LinkStatus } from './link'

const WORDS: Record<LinkStatus, string> = {
  connecting: 'Connecting',
  alone: 'Waiting for the other device',
  paired: 'Paired',
  offline: 'Relay unreachable, retrying',
}

export function TopBar({ room, link, role, children }: {
  room: string
  link: { status: LinkStatus }
  role: string
  children?: ReactNode
}) {
  return (
    <header className="bar">
      <a className="brand" href="#/" style={{ color: 'inherit', textDecoration: 'none' }}>
        Lattice Lens<small>{role}</small>
      </a>
      {children}
      <span className="spacer" />
      <span className="pairing" role="status">
        <span className={`dot ${link.status}`} aria-hidden="true" />
        {WORDS[link.status]}, room <code>{room}</code>
      </span>
    </header>
  )
}
