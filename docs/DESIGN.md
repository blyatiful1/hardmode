# Design notes

Why hardmode is shaped the way it is. The model-specific benchmark history is in the
CHANGELOG; this file is the part that stays true across models and harness versions.

## The one principle

> **Move weight from advice to structure wherever a failure mode is documented and
> deterministic.**

Prose doctrine decays fastest under momentum, judgment decays next, deterministic hooks
don't decay at all. Every hook in this kit exists because a specific failure mode (claim
without evidence, reflexive tree-destroyer, grind loop, lost request across compaction)
is common enough and mechanical enough that a reminder is not sufficient — the enforcement
has to fire whether or not the model would have caught itself.

## Independent, not stronger

The kit was born on an asymmetry — *draft cheap, verify strong* — where the verifier ran
a stronger model than the drafter. On a machine where the driver is the strongest model
available, that asymmetry inverts and would be a cost bug: fanning work out to the driver
is the most expensive path, not the safest. So the surviving value of the `verifier`,
`plan-critic` and `oracle` agents is **independence, not strength**:

- a fresh context that never saw the reasoning that produced the work,
- a mandate to *refute* rather than confirm (default to "not proven"),
- a self-derived view of the changed surface (`git diff`), not the caller's file list.

They are deliberately pinned to a model *independent of* the driver (opus/sonnet), never
inheriting it. If a subtask is genuinely too hard for that tier, the main loop does it
inline rather than fanning it out.

## The escalation ladder

Instructions are advisory; hooks are deterministic; agents are independent. Match the
tool to the stakes:

1. **Trivial / read-only** → answer directly. No subagents, no hooks-driven ceremony.
2. **A change that matters** → verify empirically, back every claim with a command run
   this session (the claim-audit hook is the deterministic backstop).
3. **Multi-file / high-stakes** → the `verifier` agent (fresh context) before reporting
   done; `/paranoid-review` or `/code-review ultra` on the diff.
4. **Stuck** → two failed fixes on one symptom is the signal, not the third attempt.
   Hand all evidence to `oracle`. If its next experiment also dead-ends, the ladder ends
   at the human with a decision-ready summary — never a third blind lap.

## What the hooks assume (and how they fail)

Every hook fails **open**: on a malformed payload, a missing field, or a renamed harness
event, it exits 0 and lets the session proceed rather than breaking it. The cost of that
choice is silent inertness after a harness change — so the honest check after any Claude
Code update is `python tools/demo.py`. A green 4/4 proves the deterministic floor still
fires against the shipped hooks; a red run means a contract moved and a hook needs its
event wiring or payload parsing updated.
