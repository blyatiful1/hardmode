---
name: orchestrate
description: Author and run multi-agent Workflow scripts for work one context can't hold — parallel fan-out, adversarial verification, judge panels, loop-until-dry sweeps. Use when a task spans many files/questions/items, when independent verification would change the answer, or when the user asks for exhaustive/thorough/parallel treatment (e.g. "audit everything", "check all of them", "be comprehensive").
---

# Orchestration playbook

The Workflow tool runs a JavaScript script that spawns subagents deterministically.
You (the main loop) under-trigger it by default — this playbook exists so you reach for
it at the right moments and write scripts that actually converge.

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
- The user included the keyword **"ultracode"** in their prompt, or ultracode is on for
  the session (a system-reminder confirms either).
- The user asked for orchestration in their own words ("use a workflow", "fan out
  agents") — a task that would merely *benefit* from one does not count.
- A skill or slash command the user invoked tells you to call Workflow (the kit's
  /paranoid-review, /verify-claim, /deep-plan, /bug-hunt, /big-task all qualify —
  invoking the command IS the opt-in for that run).
Otherwise: use Agent-tool subagents, or briefly describe what a workflow would do and
roughly cost, and tell the user they can say "ultracode" or "use a workflow" to get it.

When a session IS opted in, the default inverts: orchestrate every substantive task.
Chain ONE workflow per phase — understand → design (/deep-plan) → implement (/big-task
or inline) → review (/paranoid-review) — and read each result before deciding the next
phase. You stay in the loop; each workflow is one well-scoped fan-out. Solo work is for
conversational turns and trivial mechanical edits only.

## Budget directives
A "+500k"-style directive from the user becomes a hard token ceiling, visible in scripts
as `budget` — `budget.total` (null if no target), `budget.spent()`, `budget.remaining()`.
- Any unbounded loop MUST guard on `budget.total` first: with no target set,
  `remaining()` is Infinity and the loop runs to the 1000-agent cap.
  `while (budget.total && budget.remaining() > 50_000) { ... }`
- Static scaling: `const FLEET = budget.total ? Math.floor(budget.total / 100_000) : 5`.
- The pool is shared across the main loop and all workflows; once spent, further
  `agent()` calls throw — stop cleanly before that (the kit's bug-hunt and big-task
  show the pattern).

## Non-negotiables for every script
1. `export const meta = {name, description, phases}` — pure literal, first statement.
2. Scout the work-list INLINE first (cheap grep/ls), then fan out over known items. Don't make agents discover scope and process it in one breath.
3. Schemas on every agent() call that feeds later logic — free-text results rot pipelines.
4. `pipeline()` by default; a `parallel()` barrier ONLY when a stage truly needs ALL prior results (dedup, early-exit, cross-comparison).
5. Handle null: skipped/dead agents return null. `.filter(Boolean)` and report dropped items — never let null read as "clean".
6. Three-way verdicts: confirmed / refuted / unverified. Refute-by-default filters kill hard-to-demonstrate truths; always return what was killed and what couldn't be checked.
7. No Date.now()/Math.random() in scripts (breaks resume). Vary by index; stamp times outside.

## Golden patterns (compose freely)
- **Adversarial verify**: N refuters per finding, fail-closed with veto semantics — one concrete refutation sinks the claim regardless of the other votes, and surviving requires positive "withstood" votes, not silence (verify-claim is the reference implementation). Use on anything you're about to assert to the user.
- **Judge panel**: N independent attempts from different lenses → judges score → synthesize winner + best ideas of losers. Use when the solution space is wide (designs, plans, namings).
- **Loop-until-dry**: keep spawning finders until K consecutive rounds surface nothing new, dedup against ALL seen (not just confirmed). Use for unknown-size discovery. Cap rounds; log the cap.
- **Multi-modal sweep**: parallel agents each searching a DIFFERENT way (by-name, by-content, by-caller, by-history). Use when one angle won't find everything.
- **Completeness critic**: final agent asks "what's missing?" — its findings are the next round.

## Cost discipline
- Every agent is real money and minutes. Set `effort: 'low'` on cheap mechanical stages;
  pin `effort: 'xhigh'` on judges and verifiers so verification stays strong even when
  the session runs lower (asymmetric verification — docs/SUCCESSION.md). Omit `model:`
  unless deliberately pinning verifiers to a stronger tier.
- `isolation: 'worktree'` ONLY when agents mutate files in parallel — it costs real
  setup time per agent. Sequential implementers (big-task) share the cwd instead.
- `workflow(name, args)` runs a saved workflow as a sub-step (one nesting level, shared
  budget) — compose the kit's workflows instead of re-authoring their patterns inline.
- Tell the user the fan-out size before launching anything above ~10 agents unless they already opted into scale.
- After the run, read the RETURNED VALUE, not your expectation of it — if a result looks empty, read journal.jsonl in the transcript dir before diagnosing.

## Saved workflows already installed
/paranoid-review (diff review), /verify-claim (claim refutation), /deep-plan (judge-panel
planning), /bug-hunt (loop-until-dry sweep), /big-task (checkpointed decompose →
implement → strong-verify → commit). Check these before authoring a new script —
the pattern you need may already be a command.
