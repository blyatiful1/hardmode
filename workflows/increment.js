export const meta = {
  name: 'increment',
  description: 'Implement a task in verified increments: slice it into independently checkable steps, then per slice build → fresh-context verify (read-only verifier runs the slice check itself) → one repair round → gate; halts loudly on the first slice that does not verify',
  whenToUse: 'Invoke as /hardmode:increment <task> for multi-step implementation work where each step has a runnable check. Not for one-line fixes; for genuinely open-ended architecture run /hardmode:deep-plan first and hand its plan in as the task.',
  phases: [
    { title: 'Slice', detail: 'one planner cuts the task into checkable slices' },
    { title: 'Build', detail: 'one builder per slice, sequential' },
    { title: 'Verify', detail: 'fresh-context verifier runs the slice check' },
  ],
}

const VERIFIER = 'hardmode:verifier'
const SCOUT = 'hardmode:scout'
const MAX_SLICES = 8
const RESERVE = 60_000

const task = (typeof args === 'string' && args.trim())
  ? args.trim()
  : (args && typeof args === 'object' && typeof args.task === 'string' && args.task.trim()) ? args.task.trim() : null
if (!task) return { error: 'Usage: /hardmode:increment <task description>' }

const SLICES = {
  type: 'object',
  properties: {
    slices: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          files: { type: 'array', items: { type: 'string' }, description: 'Files this slice touches' },
          check: { type: 'string', description: 'A runnable shell command that fails until this slice is done and passes once it is' },
          doneWhen: { type: 'string', description: 'Observable acceptance criterion for this slice' },
        },
        required: ['title', 'files', 'check', 'doneWhen'],
      },
    },
    endCheck: { type: 'string', description: 'The command that proves the WHOLE task is done' },
  },
  required: ['slices', 'endCheck'],
}

const BUILD = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    changed: { type: 'array', items: { type: 'string' } },
    checkOutput: { type: 'string', description: 'Decisive lines of the slice check as YOU ran it' },
    checkPassed: { type: 'boolean' },
  },
  required: ['summary', 'changed', 'checkOutput', 'checkPassed'],
}

const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail', 'unproven'], description: 'pass = the check passed in YOUR run and the diff does what doneWhen says; fail = it does not (say why); unproven = you could not run the check' },
    evidence: { type: 'string' },
  },
  required: ['verdict', 'evidence'],
}

phase('Slice')
const plan = await agent(
  `Slice this task into independently verifiable increments for the repository at the current working directory.
TASK: ${task}
Explore the code first. Produce at most ${MAX_SLICES} ordered slices; each must name the files it touches, an observable doneWhen, and a RUNNABLE shell check that fails before the slice is built and passes after (a targeted test invocation, a script, a grep against generated output). Prefer few, coherent slices over many tiny ones. Also give the endCheck for the whole task.`,
  { label: 'slice', phase: 'Slice', schema: SLICES, model: 'opus', effort: 'xhigh', agentType: SCOUT }
).catch(() => null)
if (!plan || !plan.slices?.length) return { error: 'slicer returned no slices', task }
const slices = plan.slices.slice(0, MAX_SLICES)
if (plan.slices.length > MAX_SLICES) log(`slicer produced ${plan.slices.length} slices — capped at ${MAX_SLICES}, the rest are NOT built`)
log(`${slices.length} slice(s): ${slices.map(s => s.title).join(' | ')}`)

const results = []
let halted = null
for (let i = 0; i < slices.length; i++) {
  const s = slices[i]
  const n = `${i + 1}/${slices.length}`
  if (budget.total && budget.remaining() < RESERVE) { halted = `budget floor reached before slice ${n}`; log(halted); break }

  phase('Build')
  const buildPrompt = (extra) => `Implement slice ${n} of a larger task in the repository at the current working directory.
TASK (whole): ${task}
SLICE: ${s.title}
Files in scope: ${s.files.join(', ')}
Done when: ${s.doneWhen}
Check (run it yourself after implementing, and report its decisive output): ${s.check}
Stay inside this slice's scope; do not start later slices. Do not weaken the check to make it pass.${extra ? '\n' + extra : ''}`
  let built = await agent(buildPrompt(''), { label: `build:${i + 1}`, phase: 'Build', schema: BUILD, model: 'opus' }).catch(() => null)
  if (!built) { halted = `builder for slice ${n} did not return`; log(halted); results.push({ slice: s.title, status: 'builder-died' }); break }

  phase('Verify')
  const verify = () => agent(
    `Independently verify slice ${n} of an implementation in the repository at the current working directory. You did not write it.
SLICE: ${s.title} — done when: ${s.doneWhen}
Files claimed changed: ${(built.changed ?? []).join(', ') || '(none reported)'}
Run EXACTLY this check yourself and read its output: ${s.check}
Also read \`git diff HEAD\` for the claimed files and judge whether the diff does what doneWhen says — not whether the builder says so.
verdict=pass only if the check passed in YOUR run and the diff matches doneWhen; fail with the decisive evidence; unproven if you could not run it.`,
    { label: `verify:${i + 1}`, phase: 'Verify', schema: VERDICT, model: 'opus', effort: 'xhigh', agentType: VERIFIER }
  ).catch(() => null).then(v => v ?? { verdict: 'unproven', evidence: 'verifier did not return' })

  let verdict = await verify()
  if (verdict.verdict !== 'pass') {
    log(`slice ${n} ${verdict.verdict}: ${verdict.evidence.slice(0, 160)} — one repair round`)
    phase('Build')
    const repaired = await agent(buildPrompt(`A fresh-context verifier REJECTED the first attempt (${verdict.verdict}): ${verdict.evidence}\nFix the root cause, re-run the check, report honestly.`),
      { label: `repair:${i + 1}`, phase: 'Build', schema: BUILD, model: 'opus' }).catch(() => null)
    if (repaired) built = repaired
    phase('Verify')
    verdict = await verify()
  }
  results.push({ slice: s.title, check: s.check, changed: built.changed ?? [], builderSaysPassed: built.checkPassed, verdict })
  if (verdict.verdict !== 'pass') { halted = `slice ${n} (${s.title}) did not verify after one repair: ${verdict.verdict}`; log(halted); break }
  log(`slice ${n} verified: ${s.title}`)
}

const completed = results.filter(r => r.verdict?.verdict === 'pass').length
if (!halted && completed === slices.length) log(`all ${slices.length} slice(s) verified — run the end check yourself: ${plan.endCheck}`)
return {
  task,
  endCheck: plan.endCheck,
  slices: slices.length,
  completed,
  halted,                 // null when every slice verified; otherwise WHY the run stopped
  results,
  // Honesty: a halted run left later slices unbuilt; the tree holds the verified prefix.
  notBuilt: slices.slice(completed + (halted && results.length > completed ? 1 : 0)).map(s => s.title),
}
