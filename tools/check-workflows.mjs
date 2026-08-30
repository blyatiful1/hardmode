#!/usr/bin/env node
// Syntax-check the workflow scripts in workflows/.
//
// Workflow scripts are not plain ES modules: they use top-level `return`, top-level
// `await`, and injected globals (agent, parallel, pipeline, phase, log, args, budget,
// workflow) — so `node --check` rejects them. Instead we compile each script body as
// an AsyncFunction (which permits both return and await) after stripping the
// `export ` prefix from the meta declaration. Compilation != execution: no agents run.
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'workflows')
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

// Blank out string-literal and comment CONTENT before the determinism scan, so a prompt
// that merely MENTIONS Date.now()/Math.random() (e.g. instructing a subagent to hunt for
// that anti-pattern) does not false-fail — while real code, INCLUDING code inside
// template `${...}` interpolations, is still scanned (CONF25). Meta checks above keep
// running on the raw source; only this scan needs the stripped view.
function stripStringsAndComments(src) {
  let out = ''
  const stack = [] // {type:'template'} | {type:'interp', depth}
  for (let i = 0; i < src.length; i++) {
    const c = src[i], c2 = src[i + 1]
    const top = stack[stack.length - 1]
    if (top && top.type === 'template') {
      if (c === '\\') { i++; continue }        // escape: skip next char
      if (c === '`') { stack.pop(); continue } // end of template literal
      if (c === '$' && c2 === '{') { stack.push({ type: 'interp', depth: 0 }); i++; continue }
      continue                                 // drop template text
    }
    // code context (top level or inside a ${...} interpolation)
    if (c === '/' && c2 === '/') { while (i < src.length && src[i] !== '\n') i++; continue }
    if (c === '/' && c2 === '*') { i += 2; while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++; i++; continue }
    if (c === "'" || c === '"') { i++; while (i < src.length && src[i] !== c) { if (src[i] === '\\') i++; i++ } out += ' '; continue }
    if (c === '`') { stack.push({ type: 'template' }); continue }
    if (top && top.type === 'interp') {
      if (c === '{') top.depth++
      else if (c === '}') { if (top.depth === 0) { stack.pop(); continue } top.depth-- }
    }
    out += c
  }
  return out
}

// Every agent() call must pin an explicit `model:` (opus/sonnet) — workflow agents on
// this machine must never inherit the session driver (the most expensive model on the
// box). Scanned on the string-stripped view, so a prompt that merely says "model:" is
// gone and only a real opts key counts. Reports each unpinned call site (1-indexed line).
function unpinnedAgentCalls(stripped, rawSrc) {
  const misses = []
  const re = /\bagent\s*\(/g
  let m
  while ((m = re.exec(stripped))) {
    let depth = 0, i = m.index + m[0].length - 1 // the '('
    const start = i
    for (; i < stripped.length; i++) {
      const c = stripped[i]
      if (c === '(') depth++
      else if (c === ')') { depth--; if (depth === 0) break }
    }
    if (!/\bmodel\s*:/.test(stripped.slice(start, i + 1))) {
      misses.push(rawSrc.slice(0, m.index).split('\n').length)
    }
  }
  return misses
}

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
    const stripped = stripStringsAndComments(src)
    const forbidden = FORBIDDEN.exec(stripped)
    if (forbidden) {
      throw new Error(`uses ${forbidden[0]} — non-deterministic, breaks workflow resume`)
    }
    const unpinned = unpinnedAgentCalls(stripped, src)
    if (unpinned.length) {
      throw new Error(`agent() call(s) without an explicit model: at line(s) ${unpinned.join(', ')} `
        + `— workflow agents must pin model: 'opus'/'sonnet', never inherit the driver`)
    }
    console.log(`ok: ${file}`)
  } catch (err) {
    console.error(`FAIL: ${file}: ${err.message}`)
    failed = true
  }
}
process.exit(failed ? 1 : 0)
