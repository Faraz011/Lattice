// The written explanation. Every ID in it is a button that finds that element on the graph.
import { shortId, splitIds } from '../ids'
import type { Narrative as NarrativeData } from '../types'

export function Narrative({ narrative, onFocus }: {
  narrative: NarrativeData
  onFocus: (id: string) => void
}) {
  const paragraphs = narrative.text.split(/\n\s*\n/)
  return (
    <section className="narrative" aria-label="Explanation">
      {paragraphs.map((paragraph, p) => (
        <p key={p}>
          {splitIds(paragraph).map((part, i) => (part.id
            ? (
              <button key={i} type="button" className="id-link" title={part.id}
                onClick={() => onFocus(part.id!)}>{shortId(part.id)}</button>
            )
            : <span key={i}>{part.text}</span>))}
        </p>
      ))}
      {narrative.source === 'template' && (
        <p className="muted">Written from a template, not by the model.</p>
      )}
    </section>
  )
}
