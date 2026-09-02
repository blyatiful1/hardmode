# Design notes

Why hardmode is shaped the way it is. The model-specific benchmark history is in the
CHANGELOG; this file is the part that stays true across models and harness versions.

## The one principle

> **Move weight from advice to structure wherever a failure mode is documented and
> deterministic.**

Prose doctrine decays fastest under momentum, judgment decays next, deterministic hooks
don't decay at all. Every hook in this kit exists because a specific failure mode (claim
without evidence, reflexive tree-destroyer, grind loop, lost request across compaction,
a verifier that edits what it verifies, a commit on unchecked edits) is common enough and
mechanical enough that a reminder is not sufficient — the enforcement has to fire whether
or not the model would have caught itself.

## Evidence, not claim words

The first claim-audit gate blocked once on any completion claim after any edit and then
let the session end. It was a nag, not a check: a session that ran the tests, saw them
fail, and said "all tests pass" shipped on the second stop, and edits delegated to a
subagent were invisible. The v3.1 gate reads the transcript as evidence — every tool call
has a result with `is_error`, subagents have transcripts, the current turn starts at the
last genuine user prompt — and asks one question: *did a recognised check run after the
last modification, and did it pass?* It passes silently when the answer is yes, blocks
with the specific missing evidence when it is no, and re-blocks only when the evidence
changes. The doctrine's "never say done unless you ran the check" is now a property of
the transcript, not of the model's memory.

## Independent, not stronger — and read-only by enforcement

The kit was born on an asymmetry — *draft cheap, verify strong*. On a machine where the
driver is the strongest model available, that asymmetry inverts; the surviving value of
the `verifier`, `plan-critic`, `oracle` and `scout` agents is **independence**:

- a fresh context that never saw the reasoning that produced the work,
- a mandate to *refute* rather than confirm (default to "not proven"),
- a self-derived view of the changed surface (`git diff`), not the caller's file list,
- **no ability to modify the tree** — `tools: Read, Bash, Grep, Glob` is only an
  availability list and Bash writes freely, so a PreToolUse hook denies tree writes for
  these agent types (the harness puts `agent_type` in every subagent tool payload),
- **a machine-checked output contract** for the three verdict-shaped agents (`verifier`,
  `plan-critic`, `oracle`; `scout` is free-form) — a SubagentStop hook sends back a
  verdict that lacks its VERDICT/EVIDENCE/GAPS shape, or a CONFIRMED verdict from an
  agent that ran no command at all.

They are pinned to a model independent of the driver (opus/sonnet), never inheriting it.
If a subtask is genuinely too hard for that tier, the main loop does it inline.

## The escalation ladder

Instructions are advisory; hooks are deterministic; agents are independent. Match the
tool to the stakes:

1. **Trivial / read-only** → answer directly. No subagents, no ceremony.
2. **A change that matters** → verify empirically, back every claim with a command run
   this session (the claim-audit gate is the deterministic backstop).
3. **Multi-file / high-stakes** → the `verifier` agent before reporting done;
   `/hardmode:paranoid-review` or `/code-review ultra` on the diff;
   `/hardmode:increment` when the work has checkable steps.
4. **Stuck** → two failed fixes on one symptom is the signal, not the third attempt
   (the loop alarm makes it deterministic). Hand all evidence to `oracle`. If its next
   experiment also dead-ends, the ladder ends at the human with a decision-ready summary.

## What the hooks assume (and how they fail)

Every hook fails **open**: on a malformed payload, a missing field, or a renamed harness
event, it exits 0 and lets the session proceed rather than breaking it. The cost of that
choice is silent inertness after a harness change. Three mechanisms keep that honest:

- `tools/demo.py` runs the real hooks against planted failures **and** checks
  `hooks/hooks.json` against the event names this harness dispatches; `/hardmode:selftest`
  runs it in a session, and the session-start floor check runs it automatically the first
  time the `claude` binary changes, injecting a one-line verdict.
- Every hook writes its decisions to a per-session **ledger**; the floor check writes a
  `ran` record of its own, so a session without one is a session in which hooks did not
  execute. `/hardmode:stats` reports the witnessed count next to the firing counts.
- `/hardmode:doctor` checks the install from the outside: registration and version
  drift, wiring, the settings kill switches (`disableAllHooks`, `allowManagedHooksOnly`,
  duplicate wiring), doctrine, privacy patterns, and the witness record.

The contracts the hooks depend on were verified against Claude Code 2.1.258 by running
the CLI with dumping hooks, not by reading a bundle: the event set, `last_assistant_message`
on Stop and SubagentStop, `agent_type`/`agent_id` in subagent tool payloads, `tool_result`
blocks with `is_error`, `agent_transcript_path`, PreCompact stdout becoming the
summarizer's instructions, PreToolUse `additionalContext`, and `CLAUDE_CONFIG_DIR` (not
`CLAUDE_DIR`) as the config-dir override. A future harness that moves one of them shows up
as a red demo scenario, not as a quietly missing block.
