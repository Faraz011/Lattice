// What one clicked edge or node is, and which tool calls returned it.
import { money, shortId, typologyName } from '../ids'
import type { CircuitReport, Evidence } from '../types'

interface Props {
  id: string
  evidence: Evidence | null
  report: CircuitReport | null
  onClose: () => void
}

export function Inspector({ id, evidence, report, onClose }: Props) {
  const edge = evidence?.edges.find((e) => e.id === id)
    ?? report?.edges.find((e) => e.id === id)
  const node = evidence?.nodes.find((n) => n.id === id)
  const sources: string[] = edge && 'sources' in edge && Array.isArray(edge.sources)
    ? edge.sources : []
  const attribution = report?.circuit.attribution[id]
  const inCircuit = report?.circuit.circuit_edges.includes(id)

  return (
    <aside className="inspector" aria-label="Selected evidence">
      <header>
        <h3>{edge ? (edge.kind === 'transfer' ? 'Transfer' : 'Shared device') : 'Account'}</h3>
        <button type="button" className="quiet" onClick={onClose}>Close</button>
      </header>
      <p className="id-line" title={id}>{id}</p>
      {edge && (
        <dl>
          <dt>From</dt><dd title={edge.src}>{shortId(edge.src)}</dd>
          <dt>To</dt><dd title={edge.dst}>{shortId(edge.dst)}</dd>
          {edge.amount != null && <><dt>Amount</dt><dd>{money(edge.amount)}</dd></>}
          {edge.ts && <><dt>When</dt><dd>{new Date(edge.ts).toLocaleString()}</dd></>}
          {attribution != null && (
            <><dt>Weight in verdict</dt>
              <dd>{attribution.toFixed(3)}{inCircuit ? ', part of the circuit' : ''}</dd></>
          )}
        </dl>
      )}
      {node && (
        <dl>
          <dt>Kind</dt><dd>{node.kind === 'device' ? 'device' : node.account_kind}</dd>
          {node.customer_id && <><dt>Customer</dt><dd>{shortId(node.customer_id)}</dd></>}
        </dl>
      )}
      {edge && (
        <section>
          <h4>Returned by</h4>
          {sources.length === 0 && <p className="muted">Named in the verdict report.</p>}
          <ol className="ledger">
            {sources.map((resultId) => {
              const entry = evidence?.ledger[resultId]
              return (
                <li key={resultId}>
                  <strong>{entry?.tool ?? 'tool call'}</strong>
                  {entry && <span className="muted"> at {new Date(entry.ts)
                    .toLocaleTimeString()}</span>}
                  <div className="id-line">{resultId}</div>
                  {entry && Object.keys(entry.params).length > 0 && (
                    <div className="params">{Object.entries(entry.params)
                      .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
                      .join(', ')}</div>
                  )}
                </li>
              )
            })}
          </ol>
        </section>
      )}
      {report?.circuit.typology && inCircuit && (
        <p className="muted">Removing this edge weakens the {typologyName(
          report.circuit.typology)} pattern the verdict rests on.</p>
      )}
    </aside>
  )
}
