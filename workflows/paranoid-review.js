export const meta = {
  name: 'paranoid-review',
  description: 'Exhaustive multi-agent review of the working diff: 4 parallel finder dimensions, then adversarial verification of every finding',
  whenToUse: 'Invoke as /hardmode:paranoid-review [optional scope, e.g. a path or "last commit"] before merging substantive work. Complements /code-review with coverage-first finders and a refute-by-default verify pass.',
  phases: [
    { title: 'Find', detail: 'one coverage-first reviewer per dimension' },
    { title: 'Verify', detail: 'one adversarial verifier per finding' },
  ],
}

// Plugin agents are namespaced by plugin name; a bare 'verifier' does not resolve
// and throws at spawn time (tools/check-workflows.mjs enforces this).
const VERIFIER = 'hardmode:verifier'
const SCOUT = 'hardmode:scout'

const scope = (typeof args === 'string' && args.trim())
  ? args.trim()
  : (args && typeof args === 'object' && typeof args.scope === 'string' && args.scope.trim())
    ? args.scope.trim()
    : 'the uncommitted working diff (git diff HEAD --stat then git diff HEAD); if that is empty, review the last commit (git show HEAD)'

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          title: { type: 'string' },
          detail: { type: 'string', description: 'What is wrong and the concrete failure scenario' },
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
        },
        required: ['file', 'title', 'detail', 'severity'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT = {
  type: 'object',
  properties: {
    verdict: {
      type: 'string',
      enum: ['confirmed', 'refuted', 'unverifiable'],
      description: 'confirmed = the code demonstrably has this problem; refuted = speculative or already handled; unverifiable = could not determine either way',
    },
    reason: { type: 'string', description: 'Evidence from the actual code (or a run) that decides it' },
  },
  required: ['verdict', 'reason'],
}

const DIMENSIONS = [
  ['correctness', 'logic errors, wrong edge cases, off-by-ones, broken invariants, error paths that lose data or swallow failures'],
  ['integration', 'is the new code actually wired in and called; stale references; misuse of APIs versus their real signatures in this repo'],
  ['regressions', 'behavior that used to work and this diff breaks; check the callers and consumers of every changed symbol'],
  ['security', 'injection, path traversal, unvalidated input at trust boundaries, secrets or credentials in code'],
]

// Cross-dimension dedup: first dimension to reach Verify claims a finding. The key
// includes the line AND the title (two different findings at one file:line must not
// collide); when no line is given, a slice of the detail disambiguates.
const seen = new Set()
const dedupKey = f => `${f.file}:${f.line ?? (f.detail || '').toLowerCase().slice(0, 40)}:${(f.title || '').toLowerCase().slice(0, 50)}`

// Coverage honesty: every dimension starts UNREVIEWED and is removed only when its
// finder actually returned. This survives every way a stage can die — a resolved
// null AND a throw (the budget ceiling throws inside stage 1, which would skip
// stage 2 entirely and lose the bookkeeping).
const unauditedDimensions = DIMENSIONS.map(([key]) => key)
const reviewed = key => { const i = unauditedDimensions.indexOf(key); if (i !== -1) unauditedDimensions.splice(i, 1) }

phase('Find')
const results = await pipeline(
  DIMENSIONS,
  ([key, focus]) => agent(
    `You are reviewing ${scope} in the repository at the current working directory.
Dimension: ${key} — ${focus}.
Read the diff yourself with git, then read enough surrounding code to judge in context.
Report EVERY real issue you find regardless of severity — a separate verification step filters findings, you do not. Do not report style preferences.`,
    { label: `find:${key}`, phase: 'Find', schema: FINDINGS, model: 'opus', agentType: SCOUT }
  ).catch(() => null),
  (r, [key]) => {
    if (r == null) { log(`find:${key}: FINDER DIED — this dimension is UNREVIEWED`); return [] }
    reviewed(key)
    if (budget.total && budget.remaining() < 30_000) {
      log(`find:${key}: token budget nearly spent — findings reported UNVERIFIED`)
      return (r.findings ?? []).filter(f => !seen.has(dedupKey(f)) && seen.add(dedupKey(f)))
        .map(f => ({ ...f, dimension: key, verdict: null }))
    }
    const fresh = (r.findings ?? []).filter(f => !seen.has(dedupKey(f)) && seen.add(dedupKey(f)))
    const dupes = (r.findings?.length ?? 0) - fresh.length
    if (dupes) log(`find:${key}: ${dupes} duplicate finding(s) already claimed by another dimension`)
    return parallel(fresh.map(f => () =>
      agent(
        `Adversarially verify one code-review finding in the repository at the current working directory. Try to REFUTE it: read the actual code around it, and run it if cheap to do so.
Finding (${f.severity}) in ${f.file}${f.line ? ':' + f.line : ''}: ${f.title} — ${f.detail}
verdict=confirmed only if the code demonstrably has this problem; refuted if the finding is speculative or the code already handles it; unverifiable if you genuinely cannot determine either way.`,
        // Independent verification: the read-only verifier agent (enforced by the
        // read-only hook), opus/xhigh, pinned off the driver.
        { label: `verify:${(f.file || key).split('/').pop()}`, phase: 'Verify', schema: VERDICT,
          model: 'opus', effort: 'xhigh', agentType: VERIFIER }
      ).then(v => ({ ...f, dimension: key, verdict: v }))
    )).then(judged => judged.map((j, i) => j ?? { ...fresh[i], dimension: key, verdict: null }))
  }
)

const SEVERITY_RANK = { critical: 0, major: 1, minor: 2 }
const bySeverity = (a, b) => (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3)
const all = results.filter(Boolean).flat()
const confirmed = all.filter(f => f.verdict?.verdict === 'confirmed').sort(bySeverity)
const refuted = all.filter(f => f.verdict?.verdict === 'refuted')
const unverified = all.filter(f => !f.verdict || f.verdict.verdict === 'unverifiable').sort(bySeverity)
log(`${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified of ${all.length} findings`
  + (unauditedDimensions.length ? ` — UNREVIEWED dimensions: ${unauditedDimensions.join(', ')}` : ''))
return {
  confirmed: confirmed.map(({ verdict, ...f }) => ({ ...f, evidence: verdict.reason })),
  refuted: refuted.map(({ verdict, ...f }) => ({ ...f, refutation: verdict.reason })),
  unverified: unverified.map(({ verdict, ...f }) => ({ ...f, note: verdict?.reason ?? 'verifier did not return' })),
  // Non-empty means the clean-looking lists above are missing these lenses.
  unauditedDimensions,
}
