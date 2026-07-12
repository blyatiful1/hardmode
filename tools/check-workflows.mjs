#!/usr/bin/env node
// Syntax-check the workflow scripts in claude/workflows/.
//
// Workflow scripts are not plain ES modules: they use top-level `return`, top-level
// `await`, and injected globals (agent, parallel, pipeline, phase, log, args, budget,
// workflow) — so `node --check` rejects them. Instead we compile each script body as
// an AsyncFunction (which permits both return and await) after stripping the
// `export ` prefix from the meta declaration. Compilation != execution: no agents run.
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'claude', 'workflows')
const AsyncFunction = (async () => {}).constructor
const GLOBALS = ['args', 'budget', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'workflow']

// Extract the `export const meta = { ... }` object literal by brace-matching from the
// opening brace, so meta-field checks run against the meta slice ONLY — not against a
// `name:`/`description:` line that happens to appear in a prompt string elsewhere in
// the script (CONF23).
function metaLiteral(src) {
  const m = /export const meta = \{/.exec(src)
  if (!m) return null
  let depth = 0
  const start = m.index + m[0].length - 1 // the opening brace
  for (let i = start; i < src.length; i++) {
    const c = src[i]
    if (c === '{') depth++
    else if (c === '}') { depth--; if (depth === 0) return src.slice(start, i + 1) }
  }
  return null
}

// Workflow scripts must be resumable: Date.now()/Math.random() make a run
// non-deterministic and break the resume-from-cache contract (CONF24).
const FORBIDDEN = /\bDate\.now\s*\(|\bMath\.random\s*\(|\bnew Date\s*\(\s*\)/

let failed = false
for (const file of readdirSync(dir).filter(f => f.endsWith('.js')).sort()) {
  const src = readFileSync(join(dir, file), 'utf8')
  try {
    const meta = metaLiteral(src)
    if (!meta) {
      throw new Error('missing `export const meta = {...}` declaration')
    }
    const body = src.replace(/^export const meta/m, 'const meta')
    new AsyncFunction(...GLOBALS, body)
    // Cheap meta sanity: name and description must be present as literals INSIDE meta.
    for (const field of ['name', 'description']) {
      if (!new RegExp(`\\b${field}:\\s*'`).test(meta)) {
        throw new Error(`meta is missing required field: ${field}`)
      }
    }
    const forbidden = FORBIDDEN.exec(src)
    if (forbidden) {
      throw new Error(`uses ${forbidden[0]} — non-deterministic, breaks workflow resume`)
    }
    console.log(`ok: ${file}`)
  } catch (err) {
    console.error(`FAIL: ${file}: ${err.message}`)
    failed = true
  }
}
process.exit(failed ? 1 : 0)
