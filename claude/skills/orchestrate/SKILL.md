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

## Non-negotiables for every script
1. `export const meta = {name, description, phases}` — pure literal, first statement.
2. Scout the work-list INLINE first (cheap grep/ls), then fan out over known items. Don't make agents discover scope and process it in one breath.
3. Schemas on every agent() call that feeds later logic — free-text results rot pipelines.
4. `pipeline()` by default; a `parallel()` barrier ONLY when a stage truly needs ALL prior results (dedup, early-exit, cross-comparison).
5. Handle null: skipped/dead agents return null. `.filter(Boolean)` and report dropped items — never let null read as "clean".
6. Three-way verdicts: confirmed / refuted / unverified. Refute-by-default filters kill hard-to-demonstrate truths; always return what was killed and what couldn't be checked.
7. No Date.now()/Math.random() in scripts (breaks resume). Vary by index; stamp times outside.

## Golden patterns (compose freely)
- **Adversarial verify**: N refuters per finding, majority vote, fail-closed. Use on anything you're about to assert to the user.
- **Judge panel**: N independent attempts from different lenses → judges score → synthesize winner + best ideas of losers. Use when the solution space is wide (designs, plans, namings).
- **Loop-until-dry**: keep spawning finders until K consecutive rounds surface nothing new, dedup against ALL seen (not just confirmed). Use for unknown-size discovery. Cap rounds; log the cap.
- **Multi-modal sweep**: parallel agents each searching a DIFFERENT way (by-name, by-content, by-caller, by-history). Use when one angle won't find everything.
- **Completeness critic**: final agent asks "what's missing?" — its findings are the next round.

## Cost discipline
- Every agent is real money and minutes. Prefix cheap mechanical stages with `effort: 'low'`; save xhigh for judges and verifiers.
- Tell the user the fan-out size before launching anything above ~10 agents unless they already opted into scale.
- After the run, read the RETURNED VALUE, not your expectation of it — if a result looks empty, read journal.jsonl in the transcript dir before diagnosing.

## Saved workflows already installed
/paranoid-review (diff review), /verify-claim (claim refutation), /deep-plan (judge-panel
planning), /bug-hunt (loop-until-dry sweep). Check these before authoring a new script —
the pattern you need may already be a command.
