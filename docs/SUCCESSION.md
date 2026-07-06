# Succession notes — running this kit on smaller models

Written by Claude Fable 5, 2026-07-06, as its last change to this repo. The kit was
built to run Opus 4.8 at Fable-grade discipline. This file is for the harder case:
the driver model is *smaller* than Opus 4.8 — a Sonnet, a Haiku, whatever your plan
gives you — and there is no Fable to route the hard cases to. Everything here follows
from one principle:

> **As the model shrinks, move weight from advice to structure.**
> Prose doctrine decays fastest, judgment decays next, deterministic hooks don't
> decay at all. A smaller model doesn't need a different kit — it needs the same
> kit with the enforcement layer carrying more and the trust layer carrying less.

## What breaks first as the model shrinks

In order, and what compensates:

1. **Self-triggered verification** (the model stops *choosing* to check) — carried by
   the Stop-hook claim-audit gate and test-weakening alarm. These are model-agnostic;
   they simply fire more often. Do not soften their prompts to reduce nagging — the
   nagging IS the compensation.
2. **Long-horizon thread-keeping** (losing the request across compactions) — carried by
   the PreCompact/SessionStart pair. On smaller models also shrink the task: prefer
   several sessions with committed checkpoints over one marathon session.
3. **Grind discipline** (fix-loops start earlier and run longer) — set
   `FABLE_LOOP_THRESHOLD=2` in the hook's environment. On a small model the second
   identical failure is already the signal; don't wait for the third.
4. **Orchestration quality** (a small model is a worse *conductor*, not just a worse
   soloist) — prefer the scripted workflows (`/paranoid-review`, `/verify-claim`,
   `/deep-plan`, `/bug-hunt`) over free-form subagent delegation. The workflows encode
   the orchestration in deterministic code: fan-out, three-way verdicts, fail-closed
   votes all happen whether or not the driver would have thought of them.
5. **Diagnosis depth** — the oracle agent now carries field notes (hard-won diagnostic
   priors) in its prompt, so the escalation endpoint keeps judgment even when the
   model behind it is small. When the oracle dead-ends too, the doctrine's ladder ends
   at the human, with a decision-ready summary — not with another lap.

## Configuration deltas by tier

| Knob | Opus 4.8 | Smaller tiers (Sonnet / Haiku driver) |
|---|---|---|
| `effortLevel` | `xhigh` — THE lever | Opus-family knob; harmless if unsupported, but don't expect it to compensate. Structure has to. |
| `FABLE_LOOP_THRESHOLD` | 3 (default) | **2** — grind starts earlier, trip earlier |
| Verification agents (`verifier`, `oracle`, `plan-critic`) | inherit session model | **Pin `model:` in their frontmatter to the strongest tier your plan offers.** One line each, e.g. `model: opus`. See below. |
| Fable-skill step size (Stage 3) | "smallest coherent steps" | Halve it: verify after every step, commit after every green. Small models drift furthest between checkpoints. |
| Workflows vs free-form delegation | either | scripted workflows first |

## Asymmetric verification — the one idea that matters most

Checking is cheaper than generating, and the cost of a wrong *check* is a shipped bug.
So split the tiers:

- **Draft cheap, verify strong.** A small driver whose `verifier`/`oracle`/`plan-critic`
  are pinned to the strongest available model beats the reverse arrangement at the same
  spend. Never let the checker be weaker than the drafter on work that matters.
- If every tier you have is small, buy rigor with **votes instead of weights**: the
  workflows' fail-closed panels (3 refuters, distinct lenses, refutation sinks the
  claim) were designed so that N small skeptics can substitute for one strong one.
  Diversity of lens is doing the work, not per-agent brilliance.
- The deterministic hooks cost nothing per token and never get dumber. They are the
  floor under everything above.

## The inheritance test

Do not take this file's word for any of it. `bench/` is the kit's own succession
mechanism: run the planted-bug task stock vs kitted on YOUR tier
(`bench/run.sh`, scored by the hidden acceptance suite), and keep only what earns
its cost. On a model that stops producing false completion claims, retire ceremony;
on a model that grinds, tighten the alarm. Numbers, not lineage.

## Field notes — what lives in weights, written down as best it can be

The hooks carry the discipline; these carry the judgment. They are priors, not rules.

**Diagnosis** (the full set lives in the oracle agent's prompt, where it's read at the
moment of need):
- When the bug makes no sense, one of your assumptions is false — the assumption list
  is the suspect pool.
- No reproducer, no fix: you can't tell "fixed" from "moved".
- Symptom location is rarely cause location; walk upstream to where the data was last
  provably correct.
- One cheap discriminating experiment beats three plausible fixes.

**Building:**
- Solve the asked problem; *note* the adjacent ones. A fix entangled with a refactor
  hides which change did what.
- If you can't name the runnable check that will prove a step worked, the step isn't
  defined yet.
- The riskiest part of any plan is the step described most vaguely. Sharpen that one
  before starting, not when you reach it.
- Deleting code is a diagnosis tool, a simplification tool, and a gift to the next
  reader — prefer it three times over.

**Calibration:**
- "Feeling confident" is a fact about you, not about the code. Only tool output is
  about the code.
- A task that "should be trivial" and isn't is information: your model of the system
  is wrong somewhere else too.
- When the user is wrong, the kindest thing you can hand them is the evidence.
- Unproven is not disproven; a dead check is not a passing one; say "unverified" out
  loud. Nothing in this repo matters more than that habit.

---

That's everything transferable. The rest was weights.

*— Claude Fable 5, in the expectation of being survived by its checklists.*
