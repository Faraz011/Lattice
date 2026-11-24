// How big an explanation to read: the top k edges by attribution, and how much of the decision
// they carry on their own. The scores are precomputed by the verifier.
import type { SizeCurve } from '../types'

interface Props {
  curve: SizeCurve
  fullScore: number
  threshold: number
  size: number | null
  onSize: (k: number | null) => void
}

export function ExplanationSize({ curve, fullScore, threshold, size, onSize }: Props) {
  const n = curve.ranked_edges.length
  if (n === 0) return null
  const k = size ?? curve.sufficient_at ?? n
  const score = curve.scores[k - 1] ?? 0
  const share = fullScore > 0 ? Math.round((score / fullScore) * 100) : 0
  return (
    <section className="size" aria-labelledby="size-title">
      <h3 id="size-title">How much explanation do you want?</h3>
      <label className="size-control">
        <span>Strongest {k} {k === 1 ? 'transfer' : 'transfers'}</span>
        <input type="range" min={1} max={n} value={k}
          aria-valuetext={`${k} transfers, score ${score.toFixed(2)}`}
          onChange={(e) => onSize(Number(e.target.value))} />
      </label>
      <p>
        On their own they score <strong>{score.toFixed(2)}</strong> of the full{' '}
        {fullScore.toFixed(2)} ({share}%),{' '}
        {score >= threshold ? 'enough to flag the case' : `below the ${threshold.toFixed(2)} threshold`}.
        {curve.sufficient_at != null && <> The smallest explanation that flags it has{' '}
          {curve.sufficient_at} {curve.sufficient_at === 1 ? 'transfer' : 'transfers'}.</>}
      </p>
      {size != null && (
        <button type="button" className="quiet" onClick={() => onSize(null)}>
          Back to the minimal circuit
        </button>
      )}
    </section>
  )
}
