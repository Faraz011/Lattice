// Lattice IDs as they appear in text: the same pattern the narrator is checked against.
export const ID_PATTERN =
  /\b(?:used_device|owns):[A-Za-z0-9_]+:[A-Za-z0-9_]+|\b(?:tx|acct|cust|dev|alert|case|led|act|rec)_[A-Za-z0-9]+\b/g

/** A short form for dense places: the prefix and the first six characters. */
export function shortId(id: string): string {
  if (id.startsWith('used_device:')) {
    const [, account, device] = id.split(':')
    return `${shortId(account)} on ${shortId(device)}`
  }
  const [prefix, rest] = id.split('_', 2)
  return rest ? `${prefix}_${rest.slice(0, 6)}` : id
}

export function splitIds(text: string): Array<{ text: string; id?: string }> {
  const parts: Array<{ text: string; id?: string }> = []
  let last = 0
  for (const match of text.matchAll(ID_PATTERN)) {
    const at = match.index ?? 0
    if (at > last) parts.push({ text: text.slice(last, at) })
    parts.push({ text: match[0], id: match[0] })
    last = at + match[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
}

export function money(amount: number | null | undefined): string {
  if (amount == null) return ''
  return amount.toLocaleString('en-US', { style: 'currency', currency: 'USD',
    maximumFractionDigits: 0 })
}

export function typologyName(typology: string | null | undefined): string {
  if (!typology) return 'no pattern'
  if (typology === 'open') return 'all patterns'
  return typology.replaceAll('_', ' ')
}
