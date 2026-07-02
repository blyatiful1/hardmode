export const meta = {
  name: 'bug-hunt',
  description: 'Loop-until-dry bug sweep over a codebase: rotating finder lenses hunt until 2 consecutive rounds surface nothing new, every fresh finding is adversarially verified',
  whenToUse: 'Invoke as /bug-hunt [path or focus area] to hunt latent bugs in existing code (whole repo by default). For reviewing a fresh diff use /paranoid-review instead.',
  phases: [
    { title: 'Hunt', detail: 'rotating lenses, dedup against everything seen' },
    { title: 'Verify', detail: 'adversarial check of every fresh finding' },
  ],
}

const scope = (typeof args === 'string' && args.trim())
  ? args.trim()
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
    real: { type: 'boolean' },
    reason: { type: 'string' },
  },
  required: ['real', 'reason'],
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
const key = b => `${b.file}:${(b.title || '').toLowerCase().slice(0, 60)}`

let dry = 0
for (let round = 0; round < MAX_ROUNDS && dry < 2; round++) {
  if (budget.total && budget.remaining() < 40_000) { log('token budget nearly spent — stopping early'); break }
  phase('Hunt')
  const roundLenses = Array.from({ length: LENSES_PER_ROUND },
    (_, i) => LENSES[(round * LENSES_PER_ROUND + i) % LENSES.length])
  const alreadyFound = [...seen].slice(0, 80).join('; ')

  const found = (await parallel(roundLenses.map(([name, focus]) => () =>
    agent(
      `Hunt for real bugs in ${scope}. Your lens: ${name} — ${focus}.
Read the code deeply; report EVERY real defect you find regardless of severity — a separate verification step filters, you do not. No style nits, no hypotheticals without a triggering input.
${alreadyFound ? `Already found (do NOT re-report these): ${alreadyFound}` : ''}`,
      { label: `hunt:${name}:r${round + 1}`, phase: 'Hunt', schema: BUGS }
    )
  ))).filter(Boolean).flatMap(r => r.bugs)

  const fresh = found.filter(b => !seen.has(key(b)))
  if (!fresh.length) { dry++; log(`round ${round + 1}: nothing new (dry ${dry}/2)`); continue }
  dry = 0
  fresh.forEach(b => seen.add(key(b)))
  log(`round ${round + 1}: ${fresh.length} fresh finding(s), verifying`)

  phase('Verify')
  const judged = await parallel(fresh.map(b => () =>
    agent(
      `Adversarially verify one bug report in the repository at the current working directory. Try to REFUTE it: read the code around it and, where cheap, run it with the claimed triggering input.
Bug (${b.severity}) in ${b.file}${b.line ? ':' + b.line : ''}: ${b.title} — ${b.detail}
real=true only if the code demonstrably has this defect.`,
      { label: `verify:${(b.file || '').split('/').pop()}`, phase: 'Verify', schema: VERDICT }
    ).then(v => ({ ...b, verdict: v }))
  ))
  judged.forEach((j, idx) => {
    if (!j) { unverified.push(fresh[idx]); return }
    if (j.verdict == null) unverified.push(j)
    else if (j.verdict.real) confirmed.push(j)
    else refuted.push(j)
  })
}

log(`done: ${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified (${seen.size} total found)`)
return {
  confirmed: confirmed.map(({ verdict, ...b }) => ({ ...b, evidence: verdict.reason })),
  refuted: refuted.map(({ verdict, ...b }) => ({ ...b, refutation: verdict.reason })),
  unverified: unverified.map(({ verdict, ...b }) => b),
  totalFound: seen.size,
}
