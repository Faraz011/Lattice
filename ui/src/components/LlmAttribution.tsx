// What the language model's own judgement leaned on (U17): tool results removed at random, the
// model asked again, and a sparse linear fit of how much each result moved its answer.
import { shortId } from '../ids'
import type { LLMAttribution as Attribution } from '../types'

const SHOWN = 5

export function LlmAttribution({ attribution, onFocus }: {
  attribution: Attribution
  onFocus: (id: string) => void
}) {
  const { sources, samples, full_probability: full, agreement, note, status } = attribution
  const holding = sources.filter((s) => s.circuit_edges.length > 0).length
  return (
    <section className="attribution" aria-labelledby="attribution-title">
      <h3 id="attribution-title">What the agents' judgement leaned on</h3>
      <p className="muted">
        Tool results were left out at random {samples} times and the model asked again
        {full != null && <>; with every result it put laundering at {Math.round(full * 100)}%</>}.
        A weight is how much keeping that result raised its answer.
      </p>
      {status === 'insufficient' || status === 'skipped' ? (
        <p className="muted">{note ?? 'Not enough samples to estimate weights.'}</p>
      ) : (
        <>
          <ol className="sources">
            {sources.slice(0, SHOWN).map((s) => (
              <li key={s.result_id}>
                <span className="weight">{s.weight >= 0 ? '+' : ''}{s.weight.toFixed(2)}</span>
                <span>{s.tool.replaceAll('_', ' ')}</span>
                <span className="muted" title={s.result_id}>{shortId(s.result_id)}</span>
                {s.circuit_edges.length > 0 && (
                  <button type="button" className="id-link"
                    onClick={() => onFocus(s.circuit_edges[0])}>
                    holds {s.circuit_edges.length} circuit {s.circuit_edges.length === 1
                      ? 'edge' : 'edges'}
                  </button>
                )}
              </li>
            ))}
          </ol>
          {agreement != null && (
            <p>
              Of the {holding} results that hold the scorer's circuit,{' '}
              {Math.round(agreement * holding)} are among the {holding} the model leaned on
              most.
            </p>
          )}
          {status === 'partial' && note && <p className="muted">{note}</p>}
        </>
      )}
    </section>
  )
}
