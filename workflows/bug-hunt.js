export const meta = {
  name: 'bug-hunt',
  description: 'Loop-until-dry bug sweep over a codebase: rotating finder lenses hunt until 2 consecutive rounds surface nothing new, every fresh finding is adversarially verified',
  whenToUse: 'Invoke as /hardmode:bug-hunt [path or focus area] to hunt latent bugs in existing code (whole repo by default). For reviewing a fresh diff use /hardmode:paranoid-review instead.',
  phases: [
    { title: 'Hunt', detail: 'rotating lenses, dedup against everything seen' },
    { title: 'Verify', detail: 'adversarial check of every fresh finding' },
  ],
}

const VERIFIER = 'hardmode:verifier'   // plugin agents are namespaced; a bare name throws
const SCOUT = 'hardmode:scout'

const scope = (typeof args === 'string' && args.trim())
  ? args.trim()
  : (args && typeof args === 'object' && typeof args.scope === 'string' && args.scope.trim())
    ? args.scope.trim()
    : 'the whole repository at the current working directory (skip vendored/generated code)'

const BUGS = {
  type: 'object',
  properties: {
    bugs: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          title: { type: 'string' },
          detail: { type: 'string', description: 'The defect and the concrete input/state that triggers it' },
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
        },
        required: ['file', 'title', 'detail', 'severity'],
      },
    },
  },
  required: ['bugs'],
}

const VERDICT = {
  type: 'object',
  properties: {
    verdict: {
      type: 'string',
      enum: ['confirmed', 'refuted', 'unverifiable'],
      description: 'confirmed = the code demonstrably has this defect; refuted = speculative or already handled; unverifiable = could not determine either way',
    },
    reason: { type: 'string' },
  },
  required: ['verdict', 'reason'],
}

const LENSES = [
  ['error-paths', 'error handling: swallowed exceptions, unchecked return values, resource leaks on failure paths, partial writes'],
  ['edge-inputs', 'boundary inputs: empty/huge/unicode/negative/zero, off-by-one, integer overflow, malformed data at parse sites'],
  ['state', 'state and lifecycle: race conditions, stale caches, ordering assumptions, init/teardown gaps, mutation shared across calls'],
  ['contracts', 'API contract misuse: arguments in wrong order or units, misread return shapes, deprecated/changed signatures, null vs undefined vs empty'],
  ['environment', 'environment assumptions: paths, encodings, locale, permissions, missing config defaults, works-on-my-machine constructs'],
  ['logic', 'plain logic errors: inverted conditions, wrong operator, unreachable branches, copy-paste divergence between similar blocks'],
]

const MAX_ROUNDS = 4
const LENSES_PER_ROUND = 3
const seen = new Set()
const confirmed = []
const refuted = []
const unverified = []
// Key includes the line (or, without one, a slice of the detail) AND the title: two
// different bugs in one file with similar titles must not collide.
const key = b => `${b.file}:${b.line ?? (b.detail || '').toLowerCase().slice(0, 40)}:${(b.title || '').toLowerCase().slice(0, 60)}`

let dry = 0
let stoppedForBudget = false
// A dead hunter is not a passing check: EVERY null lens invocation is tallied — before
// any early-continue, so a fully dead round is visible in the returned object too.
let deadHunterInvocations = 0
let deadRounds = 0
const deadLenses = new Set()
for (let round = 0; round < MAX_ROUNDS && dry < 2; round++) {
  if (budget.total && budget.remaining() < 40_000) { log('token budget nearly spent — stopping early'); stoppedForBudget = true; break }
  phase('Hunt')
  const roundLenses = Array.from({ length: LENSES_PER_ROUND },
    (_, i) => LENSES[(round * LENSES_PER_ROUND + i) % LENSES.length])
  const alreadyFound = [...seen].slice(0, 80).join('; ')

  const results = await parallel(roundLenses.map(([name, focus]) => () =>
    agent(
      `Hunt for real bugs in ${scope}. Your lens: ${name} — ${focus}.
Read the code deeply; report EVERY real defect you find regardless of severity — a separate verification step filters, you do not. No style nits, no hypotheticals without a triggering input.
${alreadyFound ? `Already found (do NOT re-report these): ${alreadyFound}` : ''}`,
      { label: `hunt:${name}:r${round + 1}`, phase: 'Hunt', schema: BUGS, model: 'opus', agentType: SCOUT }
    )
  ))
  results.forEach((r, i) => { if (r == null) { deadHunterInvocations++; deadLenses.add(roundLenses[i][0]) } })
  if (results.every(r => r == null)) { deadRounds++; log(`round ${round + 1}: ALL hunters died — round does not count as dry`); continue }
  const deadThisRound = results.filter(r => r == null).length
  if (deadThisRound) log(`round ${round + 1}: ${deadThisRound} of ${results.length} hunter lens(es) died — their coverage this round is missing`)
  const found = results.filter(Boolean).flatMap(r => r.bugs ?? [])

  // Dedup ATOMICALLY (filter + add in one pass) so two lenses reporting the same
  // defect in this SAME round cannot both pass.
  const fresh = found.filter(b => !seen.has(key(b)) && seen.add(key(b)))
  if (!fresh.length) { dry++; log(`round ${round + 1}: nothing new (dry ${dry}/2)`); continue }
  dry = 0
  log(`round ${round + 1}: ${fresh.length} fresh finding(s), verifying`)

  phase('Verify')
  const judged = await parallel(fresh.map(b => () =>
    agent(
      `Adversarially verify one bug report in the repository at the current working directory. Try to REFUTE it: read the code around it and, where cheap, run it with the claimed triggering input.
Bug (${b.severity}) in ${b.file}${b.line ? ':' + b.line : ''}: ${b.title} — ${b.detail}
verdict=confirmed only if the code demonstrably has this defect; refuted if it is speculative or already handled; unverifiable if you genuinely cannot determine either way.`,
      { label: `verify:${(b.file || '').split('/').pop()}`, phase: 'Verify', schema: VERDICT,
        model: 'opus', effort: 'xhigh', agentType: VERIFIER }
    ).then(v => ({ ...b, verdict: v }))
  ))
  judged.forEach((j, idx) => {
    if (!j || j.verdict == null || j.verdict.verdict === 'unverifiable') { unverified.push(j ?? fresh[idx]); return }
    if (j.verdict.verdict === 'confirmed') confirmed.push(j)
    else refuted.push(j)
  })
}

if (stoppedForBudget) log('hunt stopped early on token budget before exhaustion — coverage is NOT exhaustive')
else if (dry < 2) log(`round cap (${MAX_ROUNDS}) reached while the hunt was still surfacing new findings — coverage is NOT exhaustive`)
const SEVERITY_RANK = { critical: 0, major: 1, minor: 2 }
const bySeverity = (a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3)
log(`done: ${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified (${seen.size} total found)`
  + (deadLenses.size ? ` — coverage lost for lenses: ${[...deadLenses].join(', ')}` : ''))
return {
  confirmed: confirmed.sort(bySeverity).map(({ verdict, ...b }) => ({ ...b, evidence: verdict.reason })),
  refuted: refuted.map(({ verdict, ...b }) => ({ ...b, refutation: verdict.reason })),
  unverified: unverified.sort(bySeverity).map(({ verdict, ...b }) => ({ ...b, note: verdict?.reason ?? 'verifier did not return' })),
  totalFound: seen.size,
  // Three-way honesty: a dead hunter is not a clean sweep.
  deadHunterInvocations,
  deadRounds,
  deadLenses: [...deadLenses],
  exhaustive: !stoppedForBudget && dry >= 2 && deadLenses.size === 0,
}
