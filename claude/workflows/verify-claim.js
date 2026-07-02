export const meta = {
  name: 'verify-claim',
  description: 'Adversarially test one claim: 3 independent refuters with distinct lenses (empirical, source, edge-case), majority vote',
  whenToUse: 'Invoke as /verify-claim <claim> before acting on a diagnosis, reporting a root cause, or relying on an environment/config/third-party fact. Not for fresh implementation diffs — hand those to the verifier agent instead.',
  phases: [{ title: 'Refute' }],
}

const claim = (typeof args === 'string' && args.trim()) ? args.trim() : null
if (!claim) return { error: 'Usage: /verify-claim <claim to test>' }

const VERDICT = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    evidence: { type: 'string', description: 'The concrete command/file/scenario that decides it' },
  },
  required: ['refuted', 'evidence'],
}

const LENSES = [
  'empirically — run code or commands that would fail if the claim were false',
  'by source — read the actual files, configs, or docs the claim rests on and check they say what the claim assumes',
  'by edge case — hunt for the specific input, state, or scenario where the claim breaks',
]

phase('Refute')
const votes = (await parallel(LENSES.map((lens, i) => () =>
  agent(
    `Try to REFUTE this claim ${lens}.
Claim: "${claim}"
Work in the current directory. Cite concrete evidence for your verdict. If after honest effort you cannot decide, set refuted=true and prefix your evidence with "UNPROVEN: " — unproven claims do not pass, but they are not disproven either.`,
    { label: `refute:${i + 1}`, schema: VERDICT }
  )
))).filter(Boolean)

const lost = LENSES.length - votes.length
const passed = votes.filter(v => !v.refuted).length
const survives = passed >= 2
log(`${passed}/${votes.length} refuters could not break the claim${lost ? `; ${lost} refuter(s) did not return — treated as failed` : ''}`)
return { claim, survives, votes, lostRefuters: lost }
