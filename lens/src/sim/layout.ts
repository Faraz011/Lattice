// A small force-directed layout for the bank's accounts, computed once and seeded, so the same
// episode always draws the same way and nothing moves while transfers play.
export interface Point { x: number; y: number }

export function layout(ids: string[], links: [string, string][], width: number, height: number,
  seed = 7): Map<string, Point> {
  let s = seed
  const rand = () => ((s = (s * 16807) % 2147483647) / 2147483647)
  const pos = new Map<string, Point>(ids.map((id) => [id, { x: rand() * width, y: rand() * height }]))
  const idx = new Map(ids.map((id, i) => [id, i]))
  const edges = links.filter(([a, b]) => idx.has(a) && idx.has(b) && a !== b)
  const k = Math.sqrt((width * height) / Math.max(ids.length, 1)) * 0.75
  let temp = width / 8
  for (let iter = 0; iter < 300; iter++) {
    const disp = new Map<string, Point>(ids.map((id) => [id, { x: 0, y: 0 }]))
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos.get(ids[i])!, b = pos.get(ids[j])!
        const dx = a.x - b.x, dy = a.y - b.y
        const d = Math.max(Math.hypot(dx, dy), 0.01)
        const f = (k * k) / d
        const da = disp.get(ids[i])!, db = disp.get(ids[j])!
        da.x += (dx / d) * f; da.y += (dy / d) * f
        db.x -= (dx / d) * f; db.y -= (dy / d) * f
      }
    }
    for (const [a, b] of edges) {
      const pa = pos.get(a)!, pb = pos.get(b)!
      const dx = pa.x - pb.x, dy = pa.y - pb.y
      const d = Math.max(Math.hypot(dx, dy), 0.01)
      const f = (d * d) / k
      const da = disp.get(a)!, db = disp.get(b)!
      da.x -= (dx / d) * f; da.y -= (dy / d) * f
      db.x += (dx / d) * f; db.y += (dy / d) * f
    }
    for (const id of ids) {
      const p = pos.get(id)!, d = disp.get(id)!
      const len = Math.max(Math.hypot(d.x, d.y), 0.01)
      p.x += (d.x / len) * Math.min(len, temp)
      p.y += (d.y / len) * Math.min(len, temp)
      // a gentle pull to the middle keeps loose accounts on the page
      p.x += (width / 2 - p.x) * 0.01
      p.y += (height / 2 - p.y) * 0.01
    }
    temp *= 0.985
  }
  // Fit into the box with a margin.
  const xs = [...pos.values()].map((p) => p.x), ys = [...pos.values()].map((p) => p.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const m = 40
  for (const p of pos.values()) {
    p.x = m + ((p.x - x0) / Math.max(x1 - x0, 1)) * (width - 2 * m)
    p.y = m + ((p.y - y0) / Math.max(y1 - y0, 1)) * (height - 2 * m)
  }
  return pos
}
