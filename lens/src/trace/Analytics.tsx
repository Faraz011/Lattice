// The decision in one sentence a panel can read aloud: what it decided, because of what, and
// what would still decide it.
import type { Net } from '../model/net'
import type { Trace } from '../model/trace'

const join = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)

// One sentence a panel can read aloud.
export function sentence(net: Net, t: Trace, against: string): string {
  const d = net.outputs[t.choice].label
  if (t.reference.choice === t.choice) {
    return `It decides ${d}, as it would for ${against}: nothing here changes its mind.`
  }
  const because = t.circuit ? join(t.circuit.evidence) : 'this situation'
  let out = `It decides ${d} because of ${because}.`
  if (t.backup) {
    out += ` Without that, ${join(t.backup.evidence)} alone would still make it ${d}.`
  } else if (t.circuit) {
    out += ` Without ${because}, it would ${net.outputs[t.reference.choice].label}.`
  }
  return out
}
