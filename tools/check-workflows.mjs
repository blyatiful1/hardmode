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

let failed = false
for (const file of readdirSync(dir).filter(f => f.endsWith('.js')).sort()) {
  const src = readFileSync(join(dir, file), 'utf8')
  try {
    if (!/^export const meta = \{/m.test(src)) {
      throw new Error('missing `export const meta = {...}` declaration')
    }
    const body = src.replace(/^export const meta/m, 'const meta')
    new AsyncFunction(...GLOBALS, body)
    // Cheap meta sanity: name and description must be present as literals.
    for (const field of ['name', 'description']) {
      if (!new RegExp(`^\\s*${field}:\\s*'`, 'm').test(src)) {
        throw new Error(`meta is missing required field: ${field}`)
      }
    }
    console.log(`ok: ${file}`)
  } catch (err) {
    console.error(`FAIL: ${file}: ${err.message}`)
    failed = true
  }
}
process.exit(failed ? 1 : 0)
