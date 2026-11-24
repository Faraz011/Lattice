// "Inside the model" (U18): a static attribution graph summary for one recorded tool choice,
// produced offline by research/interp/tool_choice_attribution.ipynb. Never part of a verdict.
import { useEffect, useState } from 'react'

export interface InterpSummary {
  slug: string
  model: string
  prompt: string
  recorded_tool: string
  chosen_letter: string
  options: Array<{ letter: string; tool: string; probability: number | null }>
  features: Array<{ node_id: string; layer: string; token: string; label: string;
    effect: number; influence: number | null }>
  error_share: number
  nodes: number
  links: number
}

export const SUMMARY_URL = `${import.meta.env.BASE_URL}interp/tool-choice.json`

export function InterpView({ summary }: { summary: InterpSummary }) {
  return (
    <div className="interp">
      <h1>Inside the model</h1>
      <p className="lede">
        One recorded investigator step, restated as a multiple choice and traced through{' '}
        <strong>{summary.model}</strong>, an open model. The attribution graph shows which
        internal features push it towards the tool the investigator chose. It explains this
        open model's answer, not the production model's, and no verdict depends on it.
      </p>

      <section aria-labelledby="interp-prompt">
        <h2 id="interp-prompt">The question</h2>
        <blockquote className="prompt">{summary.prompt}</blockquote>
        <ul className="options">
          {summary.options.map((o) => (
            <li key={o.letter} className={o.letter === summary.chosen_letter ? 'chosen' : ''}>
              <span className="letter">{o.letter}</span>
              <span>{o.tool.replaceAll('_', ' ')}</span>
              <span className="muted">
                {o.probability == null ? 'not in the graph'
                  : `p = ${o.probability.toFixed(3)}`}
              </span>
              {o.letter === summary.chosen_letter && <strong>the investigator's choice</strong>}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="interp-features">
        <h2 id="interp-features">What drives answer {summary.chosen_letter}</h2>
        {summary.features.length === 0 ? (
          <p className="muted">The graph has no direct inputs to this answer's logit. The
            model may not have rated it among its likely answers.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Effect</th><th>Layer</th><th>On token</th><th>Feature</th></tr>
            </thead>
            <tbody>
              {summary.features.map((f) => (
                <tr key={f.node_id}>
                  <td className="num">{f.effect >= 0 ? '+' : ''}{f.effect.toFixed(3)}</td>
                  <td>{f.layer}</td>
                  <td><q>{f.token}</q></td>
                  <td title={f.node_id}>{f.label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">
          Effect is a feature's direct link weight into the answer's logit. Transcoders do not
          reproduce the model exactly: {Math.round(summary.error_share * 100)}% of the
          answer's direct input comes from reconstruction error. Full graph: {summary.nodes}{' '}
          nodes and {summary.links} links, explorable in circuit-tracer's viewer.
        </p>
      </section>
    </div>
  )
}

export function InterpPanel() {
  const [summary, setSummary] = useState<InterpSummary | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    fetch(SUMMARY_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setSummary)
      .catch(() => setMissing(true))
  }, [])

  if (summary) return <InterpView summary={summary} />
  if (!missing) return <p className="muted">Loading the attribution graph summary.</p>
  return (
    <div className="interp">
      <h1>Inside the model</h1>
      <p className="lede">No attribution graph has been produced yet. It is made offline, on a
        machine with a suitable GPU:</p>
      <ol className="steps">
        <li>Export one recorded investigator step with <code>python -m
          lattice.interp.tool_choice</code>.</li>
        <li>Run <code>research/interp/tool_choice_attribution.ipynb</code>.</li>
        <li>Rebuild the UI; the notebook writes <code>ui/public/interp/tool-choice.json</code>.</li>
      </ol>
      <p className="muted">research/interp/README.md has the details.</p>
    </div>
  )
}
