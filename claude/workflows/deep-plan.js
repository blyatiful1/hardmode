export const meta = {
  name: 'deep-plan',
  description: 'Judge-panel planning: 3 planners with competing philosophies explore the repo independently, 3 judges score every plan, one synthesizer merges the winner with the best ideas of the losers',
  whenToUse: 'Invoke as /deep-plan <task description> when implementation strategy is genuinely open-ended — multiple plausible architectures, unfamiliar codebase, or high cost of picking wrong. For tasks with one obvious approach, plan directly instead.',
  phases: [
    { title: 'Plan', detail: '3 independent planners, different philosophies' },
    { title: 'Judge', detail: '3 judges score all plans' },
    { title: 'Synthesize', detail: 'merge winner + best losing ideas' },
  ],
}

const task = (typeof args === 'string' && args.trim()) ? args.trim() : null
if (!task) return { error: 'Usage: /deep-plan <task description>' }

const PLAN = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'The approach in 2-3 sentences' },
    steps: { type: 'array', items: { type: 'string' }, description: 'Ordered, concrete implementation steps' },
    keyFiles: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
    endCheck: { type: 'string', description: 'The runnable command/procedure that proves the task is done' },
  },
  required: ['summary', 'steps', 'keyFiles', 'risks', 'endCheck'],
}

const SCORES = {
  type: 'object',
  properties: {
    scores: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          plan: { type: 'integer', description: '1-based plan index' },
          score: { type: 'integer', description: '0-10' },
          notes: { type: 'string', description: 'Decisive strengths/defects found against the actual code' },
        },
        required: ['plan', 'score', 'notes'],
      },
    },
  },
  required: ['scores'],
}

const PHILOSOPHIES = [
  ['pragmatist', 'minimal diff, maximal reuse of what already exists, shortest path to the end-check passing'],
  ['skeptic', 'correctness and risk first: edge cases, failure modes, migrations, what could break existing behavior'],
  ['architect', 'the shape that stays maintainable: right seams, no dead-end coupling, but NO speculative abstraction'],
]

phase('Plan')
const plans = (await parallel(PHILOSOPHIES.map(([name, philosophy]) => () =>
  agent(
    `Design an implementation plan for this task in the repository at the current working directory.
TASK: ${task}
Your planning philosophy: ${name} — ${philosophy}.
Explore the actual codebase first (read the relevant files; verify your assumptions about existing code rather than guessing). Then produce the plan. Every step must be concrete enough to execute without re-deriving intent, and the endCheck must be genuinely runnable.`,
    { label: `plan:${name}`, phase: 'Plan', schema: PLAN }
  )
))).map((p, i) => p && { ...p, philosophy: PHILOSOPHIES[i][0] }).filter(Boolean)

if (!plans.length) return { error: 'All planners failed' }
const plansText = plans.map((p, i) =>
  `PLAN ${i + 1} (${p.philosophy}): ${p.summary}\nSteps:\n${p.steps.map(s => '- ' + s).join('\n')}\nKey files: ${p.keyFiles.join(', ')}\nRisks: ${p.risks.join('; ')}\nEnd check: ${p.endCheck}`
).join('\n\n')

phase('Judge')
const JUDGE_LENSES = [
  'request coverage — does the plan deliver every part of the task, nothing quietly narrowed',
  'feasibility against the actual code — verify claimed files/APIs exist and behave as assumed; penalize plans built on wrong assumptions',
  'simplicity and risk — fewest moving parts that still handle the real edge cases; penalize speculative abstraction AND naive happy-path-only plans equally',
]
const votes = (await parallel(JUDGE_LENSES.map((lens, i) => () =>
  agent(
    `Judge these competing implementation plans for the task below. Your lens: ${lens}.
TASK: ${task}
${plansText}
Inspect the repository at the current working directory to check each plan's claims before scoring. Score each plan 0-10 through your lens with decisive notes.`,
    { label: `judge:${i + 1}`, phase: 'Judge', schema: SCORES }
  )
))).filter(Boolean)

if (!votes.length) return { error: 'All judges failed — no verdict possible', plans }
const totals = plans.map((_, i) =>
  votes.reduce((sum, v) => sum + (v.scores.find(s => s.plan === i + 1)?.score ?? 0), 0))
const winner = totals.indexOf(Math.max(...totals))
const judgeNotes = votes.flatMap(v => v.scores).map(s => `plan ${s.plan} (${s.score}/10): ${s.notes}`).join('\n')
log(`scores: ${totals.map((t, i) => `plan${i + 1}=${t}`).join(' ')} — winner: plan ${winner + 1} (${plans[winner].philosophy})`)

phase('Synthesize')
const finalPlan = await agent(
  `Synthesize the final implementation plan for this task.
TASK: ${task}
${plansText}

JUDGE VERDICTS (3 judges, different lenses):
${judgeNotes}

The winner is PLAN ${winner + 1}. Build the final plan on its spine, but graft in any losing-plan idea or judge-flagged fix that is genuinely better. Resolve every judge-flagged defect. Output the complete final plan as markdown: numbered steps, files touched per step, risks with mitigations, and the runnable end-check. It must be executable without reading the losing plans.`,
  { label: 'synthesize', phase: 'Synthesize' }
)

return { finalPlan, scores: totals, winner: `plan ${winner + 1} (${plans[winner].philosophy})`, lostPlanners: PHILOSOPHIES.length - plans.length, lostJudges: JUDGE_LENSES.length - votes.length }
