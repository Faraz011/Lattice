// The SAR draft the verifier built from the circuit report: for the analyst to review and edit.
import { useState } from 'react'

export function SarDraft({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <section className="sar" aria-labelledby="sar-title">
      <h3 id="sar-title">Suspicious activity report draft</h3>
      <p className="muted">Written only from the facts above: the circuit, the backup routes, the
        roles and the freeze assessments. Filing is simulated.</p>
      <div className="buttons">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? 'Hide draft' : 'Read draft'}
        </button>
        <button type="button" className="quiet" onClick={() => void copy()}>
          {copied ? 'Copied' : 'Copy draft'}
        </button>
      </div>
      {open && <pre className="sar-text">{text}</pre>}
    </section>
  )
}
