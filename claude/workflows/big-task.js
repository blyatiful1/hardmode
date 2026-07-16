export const meta = {
  name: 'big-task',
  description: 'Run a big task as small verified checkpoints: decompose into committable steps, then per step implement (cheap) -> adversarially verify (strong) -> commit. Halts loudly on an unfixable step, keeping every green checkpoint.',
  whenToUse: 'Invoke as /big-task <task description> when the task is too big to hold in one head — especially on a small driver model. Encodes SUCCESSION.md: shrink the step, verify after every step, commit after every green, draft cheap / verify strong. Pass --verify-model=<tier> to pin verifiers to a stronger model. Not for tasks of one or two obvious steps — do those directly.',
  phases: [
    { title: 'Decompose', detail: 'one planner splits the task into independently verifiable, committable steps; a critic attacks the split' },
    { title: 'Execute', detail: 'per step: implement -> adversarial verify -> one repair round -> commit checkpoint' },
    { title: 'Wrap', detail: 'completeness critic re-reads the ORIGINAL request against what was committed' },
  ],
}

// ---- args: task text plus optional --verify-model=<tier> / --max-steps=N flags ----
const raw = (typeof args === 'string' && args.trim()) ? args.trim() : null
if (!raw) return { error: 'Usage: /big-task <task description> [--verify-model=opus] [--max-steps=N]' }

let verifyModel = null
let maxSteps = 10
let badFlag = null
const task = raw
  .replace(/--verify-model=(\S+)/, (_, m) => { verifyModel = m; return '' })
  .replace(/--max-steps=(\S+)/, (_, n) => {
    const v = /^\d+$/.test(n) ? +n : NaN
    if (!Number.isFinite(v) || v < 1) badFlag = `--max-steps needs a positive integer, got "${n}"`
    else maxSteps = Math.min(20, v)
    return ''
  })
  .trim()
if (badFlag) return { error: `${badFlag}. Usage: /big-task <task description> [--verify-model=opus] [--max-steps=N]` }
if (!task) return { error: 'No task text left after flags. Usage: /big-task <task description> [--verify-model=opus] [--max-steps=N]' }

// Draft cheap, verify strong: the VERIFICATION roles (plan-critic, per-step verifier,
// completeness critic) run at xhigh and are pinned to the stronger model when the
// caller gives one. The PLANNERS (decompose + repair) are drafters: xhigh effort, but
// never the verify-model pin — otherwise --verify-model would silently upgrade planning
// too, contradicting the flag's meaning and the draft-cheap/verify-strong doctrine.
const strong = { effort: 'xhigh', ...(verifyModel ? { model: verifyModel } : {}) }
const planEffort = { effort: 'xhigh' }

const PLAN = {
  type: 'object',
  properties: {
    steps: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          goal: { type: 'string', description: 'One sentence: what this step delivers' },
          detail: { type: 'string', description: 'Concrete enough to execute without re-deriving intent: files to touch, approach, edge cases in scope' },
          check: { type: 'string', description: 'The runnable command(s) that prove THIS step worked — must be executable right after the step, not only at the end' },
        },
        required: ['goal', 'detail', 'check'],
      },
    },
    canonicalCheck: { type: 'string', description: "The project's full canonical check (test suite / build / verify.sh), runnable from the repo root" },
  },
  required: ['steps', 'canonicalCheck'],
}

const CRITIQUE = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['sound', 'needs-changes'] },
    problems: { type: 'array', items: { type: 'string' }, description: 'Dropped request parts, wrong codebase assumptions, steps that are not independently verifiable/committable, missing steps' },
  },
  required: ['verdict', 'problems'],
}

const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'] },
    evidence: { type: 'string', description: 'Commands run and their decisive output lines' },
    problems: { type: 'array', items: { type: 'string' }, description: 'On fail: every concrete defect found, precise enough to fix from' },
  },
  required: ['verdict', 'evidence', 'problems'],
}

// The commit agent must return the actual hash and whether it committed — free text
// "done" is not proof a commit happened (a pre-commit hook or empty stage silently
// fails it). An independent check then confirms it against real git state.
const COMMIT = {
  type: 'object',
  properties: {
    committed: { type: 'boolean', description: 'true ONLY if git commit actually created a commit' },
    hash: { type: 'string', description: 'The new commit hash (git rev-parse HEAD after committing)' },
    error: { type: 'string', description: 'The exact error if the commit did not happen (e.g. nothing staged, hook rejected)' },
  },
  required: ['committed'],
}

const COMMIT_CHECK = {
  type: 'object',
  properties: {
    clean: { type: 'boolean', description: 'git status --porcelain produced NO output (working tree fully committed)' },
    headMatches: { type: 'boolean', description: 'HEAD commit subject is exactly the expected step message' },
    head: { type: 'string', description: 'git rev-parse HEAD' },
  },
  required: ['clean', 'headMatches'],
}

// ---- Decompose ----
phase('Decompose')
const planPrompt = `Decompose this task into the smallest coherent, ORDERED implementation steps for the repository at the current working directory.
TASK: ${task}

Explore the actual codebase first; verify assumptions rather than guessing. Then produce at most ${maxSteps} steps. Every step must be:
- independently verifiable: it names a runnable check that proves it worked, executable immediately after the step;
- committable: the repo is in a coherent, green state after it (no step may leave the build broken for a later step to fix);
- small: a step a careful junior engineer could execute without asking questions.
Also identify the project's canonical full check (test suite, build, verify script). If the task is genuinely one or two steps, return exactly those — do not pad.`
let plan = await agent(planPrompt, { label: 'decompose', phase: 'Decompose', schema: PLAN, ...planEffort })
if (!plan || !plan.steps?.length) return { error: 'Decomposition failed — no plan produced' }

const planText = p => p.steps.map((s, i) => `${i + 1}. ${s.goal}\n   ${s.detail}\n   check: ${s.check}`).join('\n')
const critique = await agent(
  `Attack this decomposition of a task before execution starts. Read the repository at the current working directory to check its assumptions.
ORIGINAL TASK (verbatim): ${task}
PLAN:
${planText(plan)}
Canonical check: ${plan.canonicalCheck}

Hunt for: parts of the original task no step delivers; steps resting on wrong assumptions about the code; steps whose check would not actually catch the step failing; steps that leave the repo broken for a later step; missing wiring/registration/docs steps. Gaps and defects only.`,
  { label: 'plan-critic', phase: 'Decompose', schema: CRITIQUE, ...strong }
)
if (critique?.verdict === 'needs-changes' && critique.problems.length) {
  log(`decomposition critique: ${critique.problems.length} problem(s) — one repair round`)
  const repaired = await agent(
    `${planPrompt}

A critic found these problems in a previous decomposition attempt — your plan must resolve every one:
${critique.problems.map(p => '- ' + p).join('\n')}
Previous plan for reference:
${planText(plan)}`,
    { label: 'decompose:v2', phase: 'Decompose', schema: PLAN, ...planEffort }
  )
  if (repaired?.steps?.length) plan = repaired
  else log('repair planner failed — proceeding with the original plan plus the critique as a known risk')
}
log(`${plan.steps.length} step(s); canonical check: ${plan.canonicalCheck}`)

// ---- Execute: implement -> verify -> (repair -> re-verify) -> commit, per step ----
const done = []
let halted = null

for (let i = 0; i < plan.steps.length; i++) {
  const step = plan.steps[i]
  const n = `${i + 1}/${plan.steps.length}`
  if (budget.total && budget.remaining() < 60_000) {
    halted = { step: i + 1, reason: 'token budget nearly spent — halting with all completed checkpoints committed' }
    log(halted.reason)
    break
  }

  const implPrompt = attempt => `Execute ONE step of a larger task in the repository at the current working directory. Do exactly this step — do not start later steps, do not commit.
OVERALL TASK (context only): ${task}
STEPS ALREADY DONE: ${done.length ? done.map(d => d.goal).join('; ') : 'none'}
YOUR STEP (${n}): ${step.goal}
${step.detail}
${attempt ? `A fresh-context adversarial verifier REJECTED the previous attempt at this step with these problems — fix every one:\n${attempt.map(p => '- ' + p).join('\n')}` : ''}
Before finishing, run the step's check yourself and make it pass: ${step.check}
Never weaken a test to make it pass. Return a one-paragraph summary of what you changed (files + what) and the check output's decisive lines.`

  const verify = async () => agent(
    `You are an adversarial verifier in a fresh context; you did not write this code and owe it no loyalty. In the repository at the current working directory, verify that this step of a larger task is ACTUALLY complete and green. Uncommitted changes in the working tree are the step's work — judge those.
STEP: ${step.goal} — ${step.detail}
Run the step's own check: ${step.check}
Then run the project's canonical check: ${plan.canonicalCheck}
Also read the changed code (git diff) and hunt false-green gaps: checks that never execute the new code, weakened/skipped tests, the wrong file edited, error paths that swallow failures.
verdict=pass ONLY if both checks pass under your own execution AND the diff genuinely delivers the step. Every problem you report must be concrete enough to fix from.`,
    { label: `verify:${i + 1}`, phase: 'Execute', schema: VERDICT, ...strong }
  )

  phase('Execute')
  const impl = await agent(implPrompt(null), { label: `step:${i + 1}`, phase: 'Execute' })
  if (impl == null) { halted = { step: i + 1, reason: 'implementer died' }; break }

  let v = await verify()
  if (v?.verdict !== 'pass') {
    const problems = v?.problems?.length ? v.problems : ['verifier did not return a verdict — treat the step as unproven and re-derive from the step description']
    log(`step ${n} rejected (${problems.length} problem(s)) — one repair round`)
    const repair = await agent(implPrompt(problems), { label: `repair:${i + 1}`, phase: 'Execute' })
    v = repair == null ? null : await verify()
    if (v?.verdict !== 'pass') {
      // Stop grinding (doctrine). Leave the dirty tree for the caller. Distinguish
      // "the repair implementer died" (second verification never ran) from a genuine
      // second verification failure — the halt reason must not claim a check that
      // never executed (CONF15).
      const reason = repair == null
        ? 'repair implementer died after one rejected verification'
        : 'step failed adversarial verification twice'
      halted = { step: i + 1, goal: step.goal, reason, problems: v?.problems ?? problems, evidence: v?.evidence ?? null }
      log(`step ${n} halting (${reason}). Completed checkpoints remain committed; the failed attempt is uncommitted in the working tree.`)
      break
    }
  }

  // Checkpoint: small models drift furthest between checkpoints, so every green step
  // becomes a commit before the next step starts.
  const stepMessage = `big-task step ${i + 1}/${plan.steps.length}: ${step.goal}`
  const commit = await agent(
    `In the repository at the current working directory, commit ALL current changes as one checkpoint commit. Run: git add -A, then commit with exactly this message (no attribution lines):
${stepMessage}
Return the commit hash, or the exact error if the commit fails (nothing staged counts as an error — say so).`,
    { label: `commit:${i + 1}`, phase: 'Execute', effort: 'low', schema: COMMIT }
  )
  // Do NOT trust the commit agent's self-report: a silently-failed commit reported as
  // success would count as a checkpoint and the next step's work would mix into the same
  // dirty tree (making the halt message's "prior checkpoints are committed" a lie). An
  // independent check confirms the commit landed against real git state before advancing.
  const check = await agent(
    `In the repository at the current working directory, verify the previous step was actually committed — do NOT commit or change anything yourself.
Run: git status --porcelain (clean=true ONLY if it prints nothing) and git log -1 --format=%s (headMatches=true ONLY if that subject line is exactly: ${stepMessage}). Also return git rev-parse HEAD as head.`,
    { label: `commit-check:${i + 1}`, phase: 'Execute', effort: 'low', schema: COMMIT_CHECK }
  )
  if (!check || !check.clean || !check.headMatches) {
    const reason = 'commit not verified — working tree is not clean or HEAD does not match the step commit (checkpoint NOT safely committed)'
    const detail = check
      ? `git state after commit: clean=${check.clean}, headMatches=${check.headMatches}${commit?.error ? `; commit agent error: ${commit.error}` : ''}`
      : 'commit-check agent died — commit status unknown'
    halted = { step: i + 1, goal: step.goal, reason, problems: [detail], evidence: v.evidence }
    log(`step ${n} halting (${reason}). Prior checkpoints remain committed; THIS step's work is uncommitted in the working tree.`)
    break
  }
  done.push({ step: i + 1, goal: step.goal, evidence: v.evidence, commit: check.head ?? commit?.hash ?? '(hash unavailable)' })
  log(`step ${n} verified and committed`)
}

// ---- Wrap: completeness against the ORIGINAL request, not the plan ----
phase('Wrap')
const wrap = await agent(
  `A large task was executed as verified checkpoints in the repository at the current working directory. Re-read the ORIGINAL request below and audit completeness against what was actually committed (read git log and the diffs of the ${done.length} most recent commits). The plan is NOT the yardstick — the original request is; a plan can quietly narrow it.
ORIGINAL REQUEST (verbatim): ${task}
COMPLETED STEPS: ${done.map(d => `${d.step}. ${d.goal}`).join('; ') || 'none'}
${halted ? `EXECUTION HALTED at step ${halted.step}: ${halted.reason}` : ''}
List every part of the original request that is NOT delivered by the commits (or write "complete"), plus anything delivered but unrequested. Cite evidence.`,
  { label: 'completeness', phase: 'Wrap', ...strong }
)

return {
  task,
  stepsPlanned: plan.steps.length,
  stepsCompleted: done.length,
  checkpoints: done,
  halted,
  completeness: wrap ?? 'completeness critic died — audit against the original request manually',
}
