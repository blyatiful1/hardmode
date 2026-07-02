export const meta = {
  name: 'paranoid-review',
  description: 'Exhaustive multi-agent review of the working diff: 4 parallel finder dimensions, then adversarial verification of every finding',
  whenToUse: 'Invoke as /paranoid-review [optional scope, e.g. a path or "last commit"] before merging substantive work. Complements /code-review with coverage-first finders and a refute-by-default verify pass.',
  phases: [
    { title: 'Find', detail: 'one coverage-first reviewer per dimension' },
    { title: 'Verify', detail: 'one adversarial verifier per finding' },
  ],
}

const scope = (typeof args === 'string' && args.trim())
  ? args.trim()
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
    real: { type: 'boolean' },
    reason: { type: 'string', description: 'Evidence from the actual code (or a run) that confirms or refutes' },
  },
  required: ['real', 'reason'],
}

const DIMENSIONS = [
  ['correctness', 'logic errors, wrong edge cases, off-by-ones, broken invariants, error paths that lose data or swallow failures'],
  ['integration', 'is the new code actually wired in and called; stale references; misuse of APIs versus their real signatures in this repo'],
  ['regressions', 'behavior that used to work and this diff breaks; check the callers and consumers of every changed symbol'],
  ['security', 'injection, path traversal, unvalidated input at trust boundaries, secrets or credentials in code'],
]

phase('Find')
const results = await pipeline(
  DIMENSIONS,
  ([key, focus]) => agent(
    `You are reviewing ${scope} in the repository at the current working directory.
Dimension: ${key} — ${focus}.
Read the diff yourself with git, then read enough surrounding code to judge in context.
Report EVERY real issue you find regardless of severity — a separate verification step filters findings, you do not. Do not report style preferences.`,
    { label: `find:${key}`, phase: 'Find', schema: FINDINGS }
  ),
  (r, [key]) => parallel((r?.findings ?? []).map(f => () =>
    agent(
      `Adversarially verify one code-review finding in the repository at the current working directory. Try to REFUTE it: read the actual code around it, and run it if cheap to do so.
Finding (${f.severity}) in ${f.file}${f.line ? ':' + f.line : ''}: ${f.title} — ${f.detail}
Set real=true only if the code demonstrably has this problem; if the finding is speculative or the code already handles it, real=false.`,
      { label: `verify:${(f.file || key).split('/').pop()}`, phase: 'Verify', schema: VERDICT }
    ).then(v => ({ ...f, dimension: key, verdict: v }))
  ))
)

const all = results.filter(Boolean).flat().filter(Boolean)
const confirmed = all.filter(f => f.verdict?.real === true)
const refuted = all.filter(f => f.verdict?.real === false)
const unverified = all.filter(f => f.verdict == null)
log(`${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified of ${all.length} findings`)
return {
  confirmed: confirmed.map(({ verdict, ...f }) => ({ ...f, evidence: verdict.reason })),
  refuted: refuted.map(({ verdict, ...f }) => ({ ...f, refutation: verdict.reason })),
  unverified: unverified.map(({ verdict, ...f }) => f),
}
