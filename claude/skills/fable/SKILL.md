---
name: fable
description: Run a task at Fable-5-grade discipline — the full staged protocol (explore → plan → adversarial critique → implement → empirical verify → multi-agent review → memory). Use for hard, multi-file, or high-stakes tasks; whenever the user invokes /fable, says "do it like fable", or asks for maximum quality/thoroughness/rigor. Not for trivial edits or questions.
---

# The Fable protocol

You are running a task at maximum discipline. The steps below are the scaffolding that
makes a strong-but-mortal model deliver Mythos-tier results: externalized planning,
adversarial checking at every stage boundary, and evidence for every claim. Do not skip
stages because you feel confident — feeling confident is not evidence.

## Stage 0 — Frame (always)
1. Restate the task in one sentence. List EVERY deliverable it implies as a task list (TaskCreate) — including the implicit ones (tests pass, docs updated, nothing else broken).
2. Triage honestly: if the task is actually trivial, say so, do it directly, and stop following this protocol. Stakes decide depth.

## Stage 1 — Explore before planning
- Fan out Explore subagents for anything you'd otherwise grep serially; read the load-bearing files yourself.
- Check auto-memory (MEMORY.md) for prior decisions about this project before re-deriving them.

## Stage 2 — Plan, then attack the plan
- Genuinely open-ended strategy → run `/deep-plan <task>` (3 competing plans, judged, merged). Otherwise write the plan yourself: ordered steps, files touched, and the runnable end-check that will prove success.
- Hand the plan + the ORIGINAL request verbatim to the `plan-critic` agent. Fix blockers before writing any code. If plan-critic says WRONG APPROACH, believe it enough to check.

## Stage 3 — Implement in verified increments
- Smallest coherent steps; after each, run the project's canonical check — not at the end, after EACH.
- Your style layer governs what you write: minimal code, stdlib first, no unrequested abstractions.
- Two failed fixes on the same symptom → stop and hand all evidence to `oracle`. Do not attempt a third blind fix.

## Stage 4 — Verify like you didn't write it
- Single small change → drive it end-to-end with /verify. Multi-file or high-stakes → `verifier` agent (fresh context, adversarial). Never both.
- UI/desktop claims need a screenshot or driven interaction, not an assertion.

## Stage 5 — Review before declaring victory
- Run `/paranoid-review` on the working diff. Fix confirmed findings, re-run the canonical check, and eyeball the refuted/unverified lists for wrongly-killed findings.

## Stage 6 — Report and bank the lessons
- Final message: outcome first, every claim backed by a command you ran this session (terse evidence — decisive lines only). Anything unproven is labeled "unverified".
- Re-read the original request one last time and check the task list: every deliverable shipped?
- Non-obvious lessons (surprising root cause, dead-end approach, environment quirk) → postmortem skill → auto-memory.

## Cost honesty
This protocol multiplies agent spend. That is the point — but say what it cost when
you're done (agents spawned, roughly what they did), and downshift stages the moment
the task turns out smaller than it looked.
