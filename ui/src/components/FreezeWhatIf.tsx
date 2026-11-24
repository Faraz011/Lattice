// "What if we freeze this account?" Each account on a route, with what freezing it would do to
// this evidence. Precomputed by the verifier (explain/routes.py); nothing is rescored here.
import { shortId } from '../ids'
import type { FreezeWhatIf as WhatIf } from '../types'

interface Props {
  whatifs: WhatIf[]
  threshold: number
  active: string | null
  onSelect: (account: string | null) => void
  onFocus: (id: string) => void
}

export function freezeVerdict(w: WhatIf, threshold: number): string {
  if (!w.still_flagged) {
    return `The case no longer flags: the score falls from ${w.score_before.toFixed(2)} to ` +
      `${w.score_after.toFixed(2)}, below ${threshold.toFixed(2)}. This account is essential to ` +
      'the evidence.'
  }
  return `The case still flags at ${w.score_after.toFixed(2)}. Another route of ` +
    `${w.backup_edges.length} transfers, dashed on the graph, still proves it.`
}

export function FreezeWhatIf({ whatifs, threshold, active, onSelect, onFocus }: Props) {
  const chosen = whatifs.find((w) => w.account_id === active) ?? null
  const essential = whatifs.filter((w) => !w.still_flagged).length
  return (
    <section className="whatif" aria-labelledby="whatif-title">
      <h3 id="whatif-title">What if we freeze an account?</h3>
      <p className="muted">
        Freezing an account removes every transfer it took part in from this evidence. Pick one
        to see whether the case still stands. {essential === 0
          ? 'No single account here is essential.'
          : `${essential} of ${whatifs.length} would stop it on their own.`}
      </p>
      <ul className="whatif-accounts">
        {whatifs.map((w) => {
          const on = w.account_id === active
          return (
            <li key={w.account_id}>
              <button type="button" aria-pressed={on} className={on ? 'toggle on' : 'toggle'}
                title={w.account_id} onClick={() => onSelect(on ? null : w.account_id)}>
                Freeze {shortId(w.account_id)}{w.role ? `, ${w.role}` : ''}
              </button>
              <span className={w.still_flagged ? 'muted' : 'essential'}>
                {w.still_flagged ? 'case holds' : 'case falls'}
              </span>
            </li>
          )
        })}
      </ul>
      {chosen && (
        <p className="whatif-result" role="status">
          {freezeVerdict(chosen, threshold)}{' '}
          {chosen.backup_edges.length > 0 && (
            <button type="button" className="id-link"
              onClick={() => onFocus(chosen.backup_edges[0])}>Show the route</button>
          )}
        </p>
      )}
    </section>
  )
}
