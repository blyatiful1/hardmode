---
name: hardmode
description: Run a task in hard mode — the staged discipline protocol (frame → explore → plan + adversarial critique → implement in verified increments → independent verify → review → bank lessons). Use for hard, multi-file, or high-stakes tasks; whenever the user invokes /hardmode, says "hard mode", or asks for maximum quality/thoroughness/rigor. Not for trivial edits or questions.
---

# Hardmode

Discipline scaffolding for work that matters: externalized framing, adversarial checking
at stage boundaries, evidence for every claim. Feeling confident is not evidence. Each
stage ROUTES to the machinery that owns the job (doctrine: "Who owns what") — a stage
never restates doctrine, it executes it.

## Stage 0 — Frame, then triage (always)
1. Restate the task in one sentence. List EVERY deliverable it implies as an explicit
   task list — including the implicit ones (tests pass, docs updated, nothing else
   broken).
2. Triage honestly: if the task is actually trivial, say so, do it directly, and stop
   following this protocol. Stakes decide depth — and downshift stages the moment the
   task turns out smaller than it looked.

## Stage 1 — Explore before planning
Read the load-bearing files yourself; delegate broad sweeps instead of grepping serially
in your own context. Check auto-memory before re-deriving prior decisions about this
project.

## Stage 2 — Plan, then attack the plan
Write the plan: ordered steps, files touched, and the runnable end-check that will prove
success. (/deep-plan only when strategy is genuinely open-ended — multiple plausible
architectures.) Hand the plan + the ORIGINAL request verbatim to `plan-critic`. Fix
blockers before writing any code. If it says WRONG APPROACH, believe it enough to check.

## Stage 3 — Implement in verified increments
Smallest coherent steps; run the project's canonical check after EACH, not at the end.
Two failed fixes on the same symptom → stop and hand all evidence to `oracle`; never a
third blind fix. Website/web-UI deliverable → the ultraweb suite owns the design
decisions inside these stages.

## Stage 4 — Verify like you didn't write it
Single small change → drive it end-to-end yourself with real inputs. Multi-file or
high-stakes → `verifier` agent (fresh context, tries to REFUTE, subsumes the canonical
check). One or the other, never both. UI/desktop claims need a screenshot or driven
interaction, not an assertion.

## Stage 5 — Review before declaring victory
Working diff → /code-review at high effort by default; /paranoid-review when the session
is orchestration-opted-in and the stakes justify a ~20-agent fan-out. Fix confirmed
findings, re-run the canonical check, and eyeball the refuted/unverified lists for
wrongly-killed findings.

## Stage 6 — Report and bank the lessons
Final message: outcome first, every claim backed by a command run this session (terse
evidence — decisive lines only); anything unproven is labeled "unverified". Re-read the
original request one last time against the task list: every deliverable shipped?
Non-obvious lessons → postmortem skill — and register memdb keywords, or the banked
memory is invisible to recall.

## Orchestration and cost
Workflow-tool stages run ONLY under the opt-in rule (the orchestrate skill owns it);
invoking this skill does not by itself authorize Workflow runs. Without the opt-in, run
the same stage with Agent-tool subagents — degrade the machinery, never the rigor.
Every workflow agent() call pins `model: 'opus'` or `'sonnet'`. This protocol multiplies
agent spend on purpose — say what it cost when you're done (agents spawned, roughly what
they did).
