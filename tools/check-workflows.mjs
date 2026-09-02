#!/usr/bin/env node
// Lint the kit's workflow scripts (workflows/*.js) — or one script via --script <path>.
//
// Workflow scripts are not plain ES modules: they use top-level `return`, top-level
// `await`, and injected globals (agent, parallel, pipeline, phase, log, args, budget,
// workflow) — so `node --check` rejects them. Each script body is compiled as an
// AsyncFunction after stripping the `export ` prefix from the meta declaration.
// Compilation != execution: no agents run.
//
// Rules (each one caught a real shipped defect or a documented runtime failure):
//   * `export const meta = {...}` must be the FIRST statement, a PURE literal (string
//     values only for name/description/title — no calls, spreads, identifiers,
//     operators, template interpolation), with string `name` and `description`;
//   * every phase('X') call / opts.phase 'X' must name a title in meta.phases (when
//     meta.phases is declared);
//   * every agent() call pins `model:` at the TOP LEVEL of its opts (a schema property
//     named `model` does not count); opts may be a const object or a spread of one;
//   * every literal agentType names an agent that exists: a kit agent under its
//     plugin-namespaced id (`hardmode:verifier` — the bare name throws at spawn),
//     or a harness built-in; a const bound to such a string is accepted;
//   * every `schema:` is an object schema whose TOP-LEVEL type is 'object';
//   * no Date.now() / Math.random() / new Date (breaks resume);
//   * no host APIs (require, process, console, fs, import()) — the runtime has none.
// Line numbers are exact: the scan views are length-preserving. A linter crash is
// reported as a LINTER BUG (exit 2), never as a script defect.
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const ROOT = join(here, '..')
const AsyncFunction = (async () => {}).constructor
const GLOBALS = ['args', 'budget', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'workflow']
const PLUGIN_NAME = (() => {
  try { return JSON.parse(readFileSync(join(ROOT, '.claude-plugin', 'plugin.json'), 'utf8')).name } catch { return 'hardmode' }
})()
const BUILTIN_AGENTS = ['general-purpose', 'Explore', 'Plan', 'claude', 'claude-code-guide', 'statusline-setup']
const IDENT = /^[A-Za-z_$][\w$]*$/

function kitAgents() {
  const dir = join(ROOT, 'agents')
  if (!existsSync(dir)) return []
  return readdirSync(dir).filter(f => f.endsWith('.md')).map(f => {
    const m = /^---[\s\S]*?\nname:\s*([^\n]+)/.exec(readFileSync(join(dir, f), 'utf8'))
    return (m ? m[1].trim() : basename(f, '.md'))
  })
}

// Two length-preserving views. `code`: strings, template text and comments blanked
// (for structure: braces, keys, FORBIDDEN / globals). `lit`: comments and template
// TEXT blanked but plain quoted strings kept (for reading literal values). Regex
// literals are recognised in code context so a quote inside one cannot swallow the
// rest of the file. Newlines are always kept, so offsets map 1:1 to lines.
const REGEX_PREV = /[(,=:\[!&|?{};+\-*%<>~^]$|\breturn$|\btypeof$|\bcase$|^$/
function views(src) {
  let code = '', lit = ''
  const stack = []
  const blank = (s) => s.replace(/[^\n]/g, ' ')
  let i = 0
  while (i < src.length) {
    const c = src[i], c2 = src[i + 1]
    const top = stack[stack.length - 1]
    if (top && top.type === 'template') {
      if (c === '\\') { code += '  '; lit += '  '; i += 2; continue }
      if (c === '`') { stack.pop(); code += ' '; lit += ' '; i++; continue }
      if (c === '$' && c2 === '{') { stack.push({ type: 'interp', depth: 0 }); code += '  '; lit += '  '; i += 2; continue }
      code += c === '\n' ? '\n' : ' '; lit += c === '\n' ? '\n' : ' '; i++; continue
    }
    if (c === '/' && c2 === '/') { const j = src.indexOf('\n', i); const end = j === -1 ? src.length : j; code += blank(src.slice(i, end)); lit += blank(src.slice(i, end)); i = end; continue }
    if (c === '/' && c2 === '*') { let j = src.indexOf('*/', i + 2); j = j === -1 ? src.length : j + 2; code += blank(src.slice(i, j)); lit += blank(src.slice(i, j)); i = j; continue }
    if (c === "'" || c === '"') {
      let j = i + 1
      while (j < src.length && src[j] !== c && src[j] !== '\n') { if (src[j] === '\\') j++; j++ }
      j = Math.min(j + 1, src.length)
      code += blank(src.slice(i, j)); lit += src.slice(i, j); i = j; continue
    }
    if (c === '`') { stack.push({ type: 'template' }); code += ' '; lit += ' '; i++; continue }
    if (c === '/') {
      const prev = code.replace(/\s+$/, '')
      if (REGEX_PREV.test(prev.slice(-8))) {
        let j = i + 1, inClass = false
        while (j < src.length && src[j] !== '\n') {
          if (src[j] === '\\') { j += 2; continue }
          if (inClass) { if (src[j] === ']') inClass = false }
          else if (src[j] === '[') inClass = true
          else if (src[j] === '/') break
          j++
        }
        j = Math.min(j + 1, src.length)
        while (j < src.length && /[a-z]/.test(src[j])) j++
        code += blank(src.slice(i, j)); lit += blank(src.slice(i, j)); i = j; continue
      }
    }
    if (top && top.type === 'interp') {
      if (c === '{') top.depth++
      else if (c === '}') { if (top.depth === 0) { stack.pop(); code += ' '; lit += ' '; i++; continue } top.depth-- }
    }
    code += c; lit += c; i++
  }
  return { code, lit }
}

const lineOf = (src, idx) => src.slice(0, idx).split('\n').length

// Matching close bracket for the bracket at `open`, walked on the CODE view (strings blanked).
function balanced(code, open) {
  let depth = 0
  for (let i = open; i < code.length; i++) {
    const ch = code[i]
    if (ch === '(' || ch === '[' || ch === '{') depth++
    else if (ch === ')' || ch === ']' || ch === '}') { depth--; if (depth === 0) return i }
  }
  return code.length - 1
}

// Top-level keys of an object literal spanning code[open..close]: [{key, valueStart}]
function topKeys(code, open, close) {
  const keys = []
  let depth = 0
  for (let i = open; i <= close; i++) {
    const ch = code[i]
    if (ch === '{' || ch === '[' || ch === '(') { depth++; continue }
    if (ch === '}' || ch === ']' || ch === ')') { depth--; continue }
    if (depth === 1) {
      const m = /^([A-Za-z_$][\w$]*|'[^']*'|"[^"]*")\s*:/.exec(code.slice(i, i + 80))
      if (m && (i === open + 1 || /[\s,{]/.test(code[i - 1]))) {
        keys.push({ key: m[1].replace(/^['"]|['"]$/g, ''), valueStart: i + m[0].length, at: i })
        i += m[0].length - 1
      }
    }
  }
  return keys
}

// The literal string value starting at `at` in the RAW source, if it is a plain string
// (quoted, or a template literal without interpolation). Otherwise null.
function stringValue(src, at) {
  const rest = src.slice(at).replace(/^\s+/, '')
  const m = /^(['"])((?:\\.|(?!\1)[^\\\n])*)\1/.exec(rest) || /^`((?:\\.|[^\\`$]|\$(?!\{))*)`/.exec(rest)
  if (!m) return null
  return m[2] !== undefined ? m[2] : m[1]
}

function constObject(code, name) {
  if (!IDENT.test(name)) return null
  const decl = new RegExp(`\\b(?:const|let|var)\\s+${name.replace(/\$/g, '\\$')}\\s*=\\s*\\{`).exec(code)
  if (!decl) return null
  const open = decl.index + decl[0].length - 1
  return { open, close: balanced(code, open) }
}

function constString(lit, name) {
  if (!IDENT.test(name)) return null
  const decl = new RegExp(`\\bconst\\s+${name.replace(/\$/g, '\\$')}\\s*=\\s*(['"])([^'"]*)\\1`).exec(lit)
  return decl ? decl[2] : null
}

// Is the object literal at code[open..close] a JSON schema whose TOP-LEVEL type is 'object'?
function isObjectSchema(src, code, open, close) {
  const t = topKeys(code, open, close).find(k => k.key === 'type')
  return !!t && stringValue(src, t.valueStart) === 'object'
}

const FORBIDDEN = /\bDate\.now\s*\(|\bMath\.random\s*\(|\bnew\s+Date\b/
const HOST = /\brequire\s*\(|\bprocess\s*\.|\bconsole\s*\.|\bimport\s*\(|\bglobalThis\b|\bfs\s*\.\s*(?:read|write)/

export function lint(src, { agents = [], plugin = PLUGIN_NAME } = {}) {
  const errors = []
  const { code, lit } = views(src)

  // meta: first statement, pure literal, string name/description
  const head = /^(?:\s|\/\/[^\n]*|\/\*[\s\S]*?\*\/)*export\s+const\s+meta\s*=\s*(?=\{)/.exec(src)
  const anywhere = /\bexport\s+const\s+meta\s*=\s*(?=\{)/.exec(code)
  if (!anywhere) { errors.push('missing `export const meta = {...}` declaration'); return errors }
  if (!head) errors.push(`\`export const meta\` must be the FIRST statement of the script (line ${lineOf(src, anywhere.index)}) — the harness rejects anything before it`)
  const metaOpen = anywhere.index + anywhere[0].length
  const metaClose = balanced(code, metaOpen)
  const metaCode = code.slice(metaOpen, metaClose + 1)
  if (/[(`+\-*/%?]|\.\.\./.test(metaCode.replace(/[\s{}\[\],:]/g, '').replace(/-/g, m => m)) && /[(`?]|\.\.\.|\s[+\-*/%]\s/.test(metaCode)) {
    errors.push(`meta must be a pure literal (no calls, spreads, operators, template interpolation) — line ${lineOf(src, metaOpen)}`)
  }
  const mkeys = topKeys(code, metaOpen, metaClose)
  for (const field of ['name', 'description']) {
    const k = mkeys.find(k => k.key === field)
    if (!k) { errors.push(`meta is missing required string field: ${field}`); continue }
    if (stringValue(src, k.valueStart) === null) errors.push(`meta.${field} must be a plain string literal — meta is a pure literal, no template interpolation (line ${lineOf(src, k.valueStart)})`)
  }
  for (const k of mkeys) {
    const v = src.slice(k.valueStart).replace(/^\s+/, '')
    if (!/^(['"`\[{]|\d|true\b|false\b|null\b)/.test(v)) errors.push(`meta.${k.key} is not a literal value (line ${lineOf(src, k.valueStart)})`)
  }

  try { new AsyncFunction(...GLOBALS, src.replace(/^export const meta/m, 'const meta')) }
  catch (e) { errors.push(`does not compile: ${e.message}`); return errors }

  const forbidden = FORBIDDEN.exec(code)
  if (forbidden) errors.push(`uses ${forbidden[0].trim()} at line ${lineOf(src, forbidden.index)} — non-deterministic, breaks workflow resume`)
  const host = HOST.exec(code)
  if (host) errors.push(`uses host API ${host[0].trim()} at line ${lineOf(src, host.index)} — the workflow runtime has no Node/filesystem access`)

  // phases: titles declared in meta vs used by phase() / opts.phase (string or plain template)
  const phasesKey = mkeys.find(k => k.key === 'phases')
  const declared = []
  if (phasesKey) {
    const arrOpen = code.indexOf('[', phasesKey.valueStart)
    const arrClose = balanced(code, arrOpen)
    for (const m of code.slice(arrOpen, arrClose + 1).matchAll(/\btitle\s*:/g)) {
      const v = stringValue(src, arrOpen + m.index + m[0].length)
      if (v !== null) declared.push(v)
    }
  }
  const used = []
  for (const m of code.matchAll(/\bphase\s*\(/g)) {
    const v = stringValue(src, m.index + m[0].length)
    if (v !== null) used.push({ title: v, idx: m.index })
  }
  for (const m of code.matchAll(/\bphase\s*:/g)) {
    if (m.index >= metaOpen && m.index <= metaClose) continue
    const v = stringValue(src, m.index + m[0].length)
    if (v !== null) used.push({ title: v, idx: m.index })
  }
  if (phasesKey) {
    for (const u of used) if (!declared.includes(u.title)) errors.push(`phase '${u.title}' (line ${lineOf(src, u.idx)}) is not declared in meta.phases [${declared.join(', ')}]`)
  } else if (used.length) {
    errors.push(`meta.phases is not declared but phase() / opts.phase is used (${[...new Set(used.map(u => u.title))].join(', ')})`)
  }

  // agent() calls: model pin, agentType, schema — all read from the TOP LEVEL of opts
  const allowed = new Set([...BUILTIN_AGENTS, ...agents.map(a => `${plugin}:${a}`)])
  const bareKit = new Set(agents)
  const re = /\bagent\s*\(/g
  let m
  while ((m = re.exec(code))) {
    const open = m.index + m[0].length - 1
    const close = balanced(code, open)
    const line = lineOf(src, m.index)
    // find the second argument: the first top-level comma inside the parens
    let depth = 0, comma = -1
    for (let i = open + 1; i < close; i++) {
      const ch = code[i]
      if (ch === '(' || ch === '[' || ch === '{') depth++
      else if (ch === ')' || ch === ']' || ch === '}') depth--
      else if (ch === ',' && depth === 0) { comma = i; break }
    }
    if (comma === -1) { errors.push(`agent() at line ${line} has no opts argument — workflow agents must pin model: 'opus'/'sonnet', never inherit the driver`); continue }
    const optsText = code.slice(comma + 1, close).trim()
    let optsOpen, optsClose
    const keys = []
    if (optsText.startsWith('{')) {
      optsOpen = code.indexOf('{', comma + 1); optsClose = balanced(code, optsOpen)
      keys.push(...topKeys(code, optsOpen, optsClose))
      for (const sp of code.slice(optsOpen, optsClose + 1).matchAll(/\.\.\.([A-Za-z_$][\w$]*)/g)) {
        const co = constObject(code, sp[1])
        if (co) keys.push(...topKeys(code, co.open, co.close))
      }
    } else {
      const id = /^([A-Za-z_$][\w$]*)/.exec(optsText)
      const co = id ? constObject(code, id[1]) : null
      if (co) keys.push(...topKeys(code, co.open, co.close))
    }
    if (!keys.some(k => k.key === 'model')) errors.push(`agent() at line ${line} has no explicit top-level model: — workflow agents must pin model: 'opus'/'sonnet', never inherit the driver`)
    const at = keys.find(k => k.key === 'agentType')
    if (at) {
      let value = stringValue(src, at.valueStart)
      if (value === null) {
        const id = /^\s*([A-Za-z_$][\w$]*)\s*[,}]/.exec(src.slice(at.valueStart))
        if (id) value = constString(lit, id[1])
      }
      if (value === null) errors.push(`agentType at line ${lineOf(src, at.valueStart)} is not a string literal or a const bound to one — it cannot be checked against the agent registry`)
      else if (!allowed.has(value)) {
        const hint = bareKit.has(value) ? ` (plugin agents are namespaced: use '${plugin}:${value}' — the bare name throws at spawn time)` : ''
        errors.push(`agentType '${value}' at line ${lineOf(src, at.valueStart)} is not a known agent${hint}; known: ${[...allowed].join(', ')}`)
      }
    }
    const sc = keys.find(k => k.key === 'schema')
    if (sc) {
      const rest = code.slice(sc.valueStart).replace(/^\s+/, '')
      let ok = false
      if (rest.startsWith('{')) {
        const o = code.indexOf('{', sc.valueStart)
        ok = isObjectSchema(src, code, o, balanced(code, o))
      } else {
        const id = /^([A-Za-z_$][\w$]*)/.exec(rest)
        const co = id ? constObject(code, id[1]) : null
        if (co) ok = isObjectSchema(src, code, co.open, co.close)
      }
      if (!ok) errors.push(`schema at line ${lineOf(src, sc.valueStart)} is not an object schema (its top-level type must be 'object'; a string, array schema or unresolvable identifier is not accepted by the runtime)`)
    }
  }
  return errors
}

function main() {
  const argv = process.argv.slice(2)
  const agents = kitAgents()
  let failed = false, crashed = false
  const targets = []
  const si = argv.indexOf('--script')
  if (si !== -1) targets.push(argv[si + 1])
  else for (const f of readdirSync(join(ROOT, 'workflows')).filter(f => f.endsWith('.js')).sort()) targets.push(join(ROOT, 'workflows', f))
  for (const file of targets) {
    let errors
    try { errors = lint(readFileSync(file, 'utf8'), { agents }) }
    catch (e) { crashed = true; console.error(`LINTER BUG: ${basename(file)}: ${e.message} — this is a defect in check-workflows.mjs, not in the script`); continue }
    if (errors.length) { failed = true; for (const e of errors) console.error(`FAIL: ${basename(file)}: ${e}`) }
    else console.log(`ok: ${basename(file)}`)
  }
  process.exit(crashed ? 2 : failed ? 1 : 0)
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main()
