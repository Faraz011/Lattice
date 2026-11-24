// "Same method, on a neural network": the slot for the research results that show the evidence
// circuit's search also recovers circuits inside GPT-2. Lattice does not compute these numbers;
// they come from the research code as `ui/public/research/credibility.json`.
import { useEffect, useState } from 'react'

export interface Credibility {
  title: string
  summary: string
  model: string
  rows: Array<{ measure: string; ours: string; baseline: string; baseline_name: string
    note?: string }>
  source: string // where the numbers come from: a paper, a notebook, a commit
  caveat?: string
}

export const CREDIBILITY_URL = `${import.meta.env.BASE_URL}research/credibility.json`

export function CredibilityView({ data }: { data: Credibility }) {
  return (
    <div className="interp">
      <h1>{data.title}</h1>
      <p className="lede">{data.summary}</p>
      <table>
        <thead>
          <tr><th>Measure ({data.model})</th><th>Our search</th><th>Baseline</th><th>Note</th></tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.measure}>
              <td>{r.measure}</td>
              <td className="num">{r.ours}</td>
              <td>{r.baseline} <span className="muted">({r.baseline_name})</span></td>
              <td className="muted">{r.note ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">Source: {data.source}</p>
      {data.caveat && <p className="muted">{data.caveat}</p>}
    </div>
  )
}

export function ResearchPanel() {
  const [data, setData] = useState<Credibility | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    fetch(CREDIBILITY_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setData)
      .catch(() => setMissing(true))
  }, [])

  if (data) return <CredibilityView data={data} />
  if (!missing) return <p className="muted">Loading the research results.</p>
  return (
    <div className="interp">
      <h1>Same method, on a neural network</h1>
      <p className="lede">The search that finds an evidence circuit and its backup routes in a
        transaction graph can also find the circuit inside a language model that carries out a
        task. Results on GPT-2 go here, from the research code.</p>
      <p>Add <code>ui/public/research/credibility.json</code> with a title, a summary, the model,
        rows of measures (ours against a baseline, such as Edge Pruning) and the source of the
        numbers, then rebuild the UI. The format is in <code>docs/demo.md</code>.</p>
    </div>
  )
}
