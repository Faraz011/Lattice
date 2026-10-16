// The approver token must never be compiled into the UI: no VITE_ variable may carry it, and
// the built files must not contain the configured token value.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const dist = new URL('../dist/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const files = []
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path)
    else files.push(path)
  }
}
walk(dist)

const forbidden = [/APPROVER_TOKEN/i, /X-Approver-Token["']?\s*[:=]\s*["'][^"']+["']/]
let token = process.env.LATTICE_APPROVER_TOKEN
try {
  const env = readFileSync(new URL('../../.env', import.meta.url), 'utf8')
  token ??= env.match(/^LATTICE_APPROVER_TOKEN=(.+)$/m)?.[1]?.trim()
} catch {
  // no .env next to the project: check the patterns only
}

const problems = []
for (const file of files) {
  const text = readFileSync(file, 'utf8')
  for (const pattern of forbidden) if (pattern.test(text)) problems.push(`${file}: ${pattern}`)
  if (token && token.length >= 6 && text.includes(token)) problems.push(`${file}: token value`)
}
if (problems.length) {
  console.error('The approver token leaked into the bundle:\n' + problems.join('\n'))
  process.exit(1)
}
console.log(`Checked ${files.length} built files: no approver token.`)
