export const meta = {
  name: 'verify-claim',
  description: 'Adversarially test one claim: 3 independent refuters with distinct lenses (empirical, source, edge-case), fail-closed majority vote',
  whenToUse: 'Invoke as /verify-claim <claim> before acting on a diagnosis, reporting a root cause, or relying on an environment/config/third-party fact. Not for fresh implementation diffs — hand those to the verifier agent instead.',
  phases: [{ title: 'Refute' }],
}

const claim = (typeof args === 'string' && args.trim()) ? args.trim() : null
if (!claim) return { error: 'Usage: /verify-claim <claim to test>' }

const VERDICT = {
  type: 'object',
  properties: {
    verdict: {
      type: 'string',
      enum: ['refuted', 'withstood', 'unproven'],
      description: 'refuted = concrete evidence the claim is false; withstood = you actively tried to break it and it held; unproven = honest effort could not decide either way',
    },
    evidence: { type: 'string', description: 'The concrete command/file/scenario that decides it' },
  },
  required: ['verdict', 'evidence'],
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
Work in the current directory. Cite concrete evidence for your verdict.
verdict=refuted only with concrete evidence the claim is false; withstood only if you actively attacked it and it held; unproven if after honest effort you cannot decide — an unproven claim does not pass, but it is not disproven either.`,
    // Refuters ARE the verification layer: opus/xhigh, pinned off the driver.
    { label: `refute:${i + 1}`, schema: VERDICT, model: 'opus', effort: 'xhigh' }
  )
// A dead refuter is not a passing vote — count it as unproven, fail closed.
))).map((v, i) => ({
  lens: LENSES[i].split(' — ')[0],
  verdict: v?.verdict ?? 'unproven',
  evidence: v?.evidence ?? 'refuter did not return',
}))

const count = verdict => votes.filter(v => v.verdict === verdict).length
const survives = count('withstood') >= 2 && count('refuted') === 0
log(`withstood ${count('withstood')}, refuted ${count('refuted')}, unproven ${count('unproven')} — claim ${survives ? 'SURVIVES' : 'DOES NOT SURVIVE'}`)
return {
  claim,
  survives,
  counts: { withstood: count('withstood'), refuted: count('refuted'), unproven: count('unproven') },
  votes,
}
