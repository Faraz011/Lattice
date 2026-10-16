// "What would change the verdict": precomputed removals, shown without rescoring here.
import { shortId, typologyName } from '../ids'
import type { CircuitReport } from '../types'

interface Props {
  report: CircuitReport
  active: number | null
  onToggle: (index: number | null) => void
}

export function Counterfactuals({ report, active, onToggle }: Props) {
  const { counterfactuals, note } = report.counterfactuals
  const threshold = report.circuit.threshold
  return (
    <section className="counterfactuals" aria-labelledby="cf-title">
      <h3 id="cf-title">What would change the verdict</h3>
      {counterfactuals.length === 0 ? (
        <p className="muted">
          No counterfactual within bound: removing any one or two edges still leaves the score
          at or above {threshold.toFixed(2)}.{note ? ` ${note}` : ''}
        </p>
      ) : (
        <ul>
          {counterfactuals.map((cf, i) => {
            const on = active === i
            return (
              <li key={cf.removed.join('+')}>
                <button type="button" aria-pressed={on} className={on ? 'toggle on' : 'toggle'}
                  onClick={() => onToggle(on ? null : i)}>
                  Without {cf.removed.map(shortId).join(' and ')}
                </button>
                <span className="cf-score">
                  {report.circuit.full_score.toFixed(2)} falls to {cf.score_after.toFixed(2)}
                  {cf.typology_after && cf.typology_after !== report.circuit.typology
                    ? `, reads as ${typologyName(cf.typology_after)}` : ''}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      {active != null && (
        <p className="muted">Removed edges are dotted on the graph. The verifier computed these
          scores; nothing is rescored here.</p>
      )}
    </section>
  )
}
