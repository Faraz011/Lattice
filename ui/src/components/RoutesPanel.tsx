// The routes the money takes, and each account's role on them, read from the evidence's shape.
// Within a route every hop needs the one before (a chain: all of them); separate routes are
// backups for each other (any one of them keeps the flag).
import { shortId } from '../ids'
import type { RouteInfo } from '../types'

interface Props {
  routes: RouteInfo[]
  roles: Record<string, string>
  relation: string | null | undefined
  onFocus: (id: string) => void
}

export function RoutesPanel({ routes, roles, relation, onFocus }: Props) {
  if (routes.length === 0) return null
  return (
    <section className="routes" aria-labelledby="routes-title">
      <h3 id="routes-title">
        {routes.length === 1 ? 'One route proves this case'
          : `${routes.length} independent routes prove this case`}
      </h3>
      <ol>
        {routes.map((route, i) => (
          <li key={route.edges.join('+')}>
            <p className="route-head">
              <strong>{i === 0 ? 'Route 1, the minimal circuit' : `Route ${i + 1}, a backup`}</strong>
              <span className="muted"> {route.path.length} transfers in a chain; {route.edges.length}
                {' '}of them score {route.score.toFixed(2)} on their own</span>
            </p>
            <p className="route-path">
              {route.accounts.map((a, j) => (
                <span key={a}>
                  {j > 0 && <span aria-hidden="true"> → </span>}
                  <button type="button" className="id-link" title={a}
                    onClick={() => onFocus(a)}>{shortId(a)}</button>
                  {roles[a] && <span className="role"> {roles[a]}</span>}
                </span>
              ))}
            </p>
          </li>
        ))}
      </ol>
      {relation && <p className="muted">The routes are {relation}.</p>}
      <p className="muted">Roles come from the flow of funds in the evidence, not from labels.</p>
    </section>
  )
}
