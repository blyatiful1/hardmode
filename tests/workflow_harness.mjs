// Runs a workflow script under STUBBED runtime globals so its control flow can be tested
// without spawning agents. Usage: node workflow_harness.mjs <script.js> <spec.json>
// spec: { args, budgetTotal?, spent?, agents: { "<label>": value | [values...] } } where a
// value {"__die": true} makes agent() resolve null (skipped / died) and {"__throw": "m"}
// makes it reject. Prints {result, logs, calls} as JSON.
import { readFileSync } from 'node:fs'

const [, , scriptPath, specPath] = process.argv
const spec = JSON.parse(readFileSync(specPath, 'utf8'))
const src = readFileSync(scriptPath, 'utf8').replace(/^export const meta/m, 'const meta')
const logs = [], calls = [], counters = {}

function stubFor(label) {
  let entry = spec.agents?.[label]
  if (entry === undefined) {
    const k = Object.keys(spec.agents ?? {}).find(k => k.endsWith('*') && label.startsWith(k.slice(0, -1)))
    entry = k === undefined ? (spec.default ?? null) : spec.agents[k]
  }
  if (Array.isArray(entry)) {
    const i = counters[label] ?? 0
    counters[label] = i + 1
    entry = entry[Math.min(i, entry.length - 1)]
  }
  return entry
}

async function agent(prompt, opts = {}) {
  const label = opts.label ?? prompt.slice(0, 40)
  calls.push({ label, agentType: opts.agentType ?? null, model: opts.model ?? null, phase: opts.phase ?? null })
  const e = stubFor(label)
  if (e && typeof e === 'object' && e.__throw) throw new Error(e.__throw)
  if (e && typeof e === 'object' && e.__die) return null
  return e
}
// parallel(): a thunk that throws resolves to null; the call itself never rejects.
const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
// pipeline(): a stage that throws OR resolves null drops the item and skips its remaining stages.
const pipeline = (items, ...stages) => Promise.all(items.map(async (item, i) => {
  let v = item
  for (const st of stages) {
    try { v = await st(v, item, i) } catch { return null }
    if (v == null) return null
  }
  return v
}))
const phase = () => {}
const log = m => logs.push(String(m))
const spent = spec.spent ?? 0
const budget = {
  total: spec.budgetTotal ?? null,
  spent: () => spent,
  remaining: () => (spec.budgetTotal ? Math.max(0, spec.budgetTotal - spent) : Infinity),
}
const workflow = async () => { throw new Error('nested workflow() is not stubbed') }

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const fn = new AsyncFunction('args', 'budget', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'workflow', src)
const result = await fn(spec.args, budget, agent, parallel, pipeline, phase, log, workflow)
process.stdout.write(JSON.stringify({ result, logs, calls }))
