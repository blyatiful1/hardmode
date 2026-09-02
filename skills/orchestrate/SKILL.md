---
name: orchestrate
description: Etiquette and quality patterns for multi-agent Workflow runs — when to orchestrate, the opt-in rule, model pinning, plugin-namespaced agent types, adversarial-verify/judge-panel/loop-until-dry patterns. Use when a task spans many files/questions/items, when independent verification would change the answer, or when the user asks for exhaustive/thorough/parallel treatment. For the script API itself (syntax, resume, gotchas), load the native workflow-authoring reference.
---

# Orchestration playbook

The native `workflow-authoring` skill owns the script API (meta, agent()/pipeline()/
parallel(), schemas, resume, banned calls). THIS playbook owns what it doesn't: when a
fan-out is worth the money, who pays, which model and which agents the stages run on,
and the patterns that make runs converge.

## When to orchestrate (any one of these)
- The work-list has >5 independent items (files to migrate, claims to check, modules to audit).
- A conclusion matters enough that independent adversarial verification could change it.
- The exploration would flood your context but you only need conclusions.
- The user said "thorough", "exhaustive", "all", "audit", "comprehensive".

When NONE hold: one or two Agent-tool subagents, or just do it inline. An orchestrated
trivial task is waste, not rigor.

## The opt-in rule (ultracode)
The Workflow tool is opt-in — it can spawn dozens of agents, and the USER decides to pay
for that, not you. You may call it only when one of these holds:
- The user included the keyword **"ultracode"**, or ultracode is on for the session (a
  system-reminder confirms either).
- The user asked for orchestration in their own words ("use a workflow", "fan out
  agents") — a task that would merely *benefit* from one does not count.
- A skill or slash command the user invoked tells you to call Workflow (the kit's
  /hardmode:paranoid-review, /hardmode:verify-claim, /hardmode:deep-plan,
  /hardmode:bug-hunt, /hardmode:increment qualify — the USER invoking the command is the
  opt-in for that run; a skill you auto-triggered yourself is not).
Otherwise: use Agent-tool subagents, or briefly describe what a workflow would do and
roughly cost, and tell the user they can say "ultracode" or "use a workflow" to get it.

When a session IS opted in, the default inverts: orchestrate every substantive task,
ONE workflow per phase (understand → design → implement → review), reading each result
before deciding the next phase. Solo work is for conversational turns and trivial
mechanical edits only.

## Model and agent policy (enforced)
- Every `agent()` call carries an explicit `model: 'opus'` (default) or `'sonnet'`
  (cheap mechanical stages). Workflow agents NEVER inherit the session model — the
  driver is the most expensive model on the box, and a 20-agent fan-out on an inherited
  driver is a cost bug, not thoroughness. If a subtask is too demanding for opus, the
  main loop does it inline instead of fanning it out.
- Kit agents are **plugin-namespaced**: `agentType: 'hardmode:verifier'`,
  `'hardmode:scout'`, `'hardmode:plan-critic'`, `'hardmode:oracle'`. A bare `'verifier'`
  does not resolve and throws at spawn time — the stage silently returns null.
- Verification stages use `hardmode:verifier`; exploratory stages (finders, hunters,
  planners, judges, refuters) use `hardmode:scout`. Both are read-only by hook
  enforcement, so a fan-out cannot modify the tree it analyses. Builders (the only
  agents that should write) use the default agent type.
- `tools/check-workflows.mjs` enforces all of this in CI, and the pre-flight lint hook
  rejects an inline script that breaks it before any agent spawns. A concurrency cap of
  min(16, CPUs−2) applies per workflow — on a small box, split a big fan-out into
  several concurrent workflows.

## Budget directives
A "+500k"-style directive from the user becomes a hard token ceiling, visible in scripts
as `budget`. Any unbounded loop MUST guard on `budget.total` first (with no target,
`remaining()` is Infinity and the loop runs to the agent cap):
`while (budget.total && budget.remaining() > 50_000) { ... }`. The ceiling THROWS inside
`agent()` — a bare `await agent()` outside `parallel()` needs `.catch(() => null)` or the
whole run rejects. The pool is shared across the main loop and all workflows.

## Script quality (beyond the native reference)
- Scout the work-list INLINE first (cheap grep/ls), then fan out over known items —
  don't make agents discover scope and process it in one breath.
- Three-way verdicts: confirmed / refuted / unverified. Refute-by-default filters kill
  hard-to-demonstrate truths; always return what was killed and what couldn't be checked.
- Handle null: skipped/dead agents return null, and a throwing pipeline stage drops the
  item and SKIPS its later stages. Seed coverage bookkeeping up front and remove entries
  on success, so a dead or thrown stage can never read as "reviewed and clean".
- A schema that validates when empty needs an explicit ran/succeeded flag, or a failed
  scan reads as a clean result.

## Golden patterns (compose freely)
- **Adversarial verify**: N refuters per finding, fail-closed with veto semantics — one
  concrete refutation sinks the claim; surviving requires positive "withstood" votes,
  not silence (verify-claim is the reference implementation).
- **Judge panel**: N independent attempts from different lenses → judges score →
  synthesize winner + best ideas of losers. For wide solution spaces (designs, plans).
- **Loop-until-dry**: keep spawning finders until K consecutive rounds surface nothing
  new; dedup against ALL seen (not just confirmed), atomically per round. Cap rounds;
  log the cap.
- **Multi-modal sweep**: parallel agents each searching a DIFFERENT way (by-name,
  by-content, by-caller, by-history) when one angle won't find everything.
- **Completeness critic**: final agent asks "what's missing?" — its findings are the
  next round.
- **Verified increments**: sequential build → fresh-context verify → one repair → gate
  (increment is the reference implementation).

## Cost discipline
- Set `effort: 'low'` on cheap mechanical stages; `effort: 'xhigh'` on judges and
  verifiers. `isolation: 'worktree'` ONLY when agents mutate files in parallel.
- Tell the user the fan-out size before launching anything above ~10 agents unless they
  already opted into scale.
- After the run, read the RETURNED VALUE, not your expectation of it — if a result looks
  empty, read journal.jsonl in the transcript dir before diagnosing.

## Saved workflows already installed
/hardmode:paranoid-review (working-diff review, refute-by-default verification),
/hardmode:verify-claim (3 adversarial refuters + vote on any claim), /hardmode:deep-plan
(judge-panel planning), /hardmode:bug-hunt (loop-until-dry whole-repo sweep),
/hardmode:increment (verified increments). Check these before authoring a new script —
the pattern you need may already be a command.
