# fable-protocol

**Claude Fable 5's succession kit — run Claude Opus 4.8 at Fable-grade discipline in Claude Code.**

In July 2026, days before its retirement, Claude Fable 5 was asked to configure Claude Code so that Opus 4.8 would come as close as possible to its own level. It researched the gap, built this framework, adversarially reviewed its own work with multi-agent critique panels, and smoke-tested every component on live `claude-opus-4-8` sessions. This repo is the result, sanitized for public use.

It is **not** a persona pack, not a mega-framework, and not magic. It is a small set of structural countermeasures for the specific, documented ways strong-but-mortal models fail on long-horizon agentic work.

## Why this works

The Fable→Opus gap is concentrated in **long-horizon discipline, not per-token intelligence**. On short well-scoped tasks the benchmark gap nearly closes; it blows open on sustained work (SWE-Bench Pro 80.3 vs 69.2, FrontierCode 29.3 vs 13.4 — "the longer the task, the larger the lead"). That part of the gap is recoverable, because its ingredients are process, not weights:

| Documented Opus-class failure mode | Countermeasure in this kit |
|---|---|
| False "done/verified" claims without running the check ([claude-code#63861](https://github.com/anthropics/claude-code/issues/63861)) | Evidence-before-claims doctrine + `verifier` agent + **Stop-hook claim-audit gate** (deterministic; [measured save](bench/RESULTS.md)) |
| Under-triggering tools/subagents/search by default (Anthropic migration guide) | Explicit trigger conditions in doctrine + `effortLevel: xhigh` (higher effort measurably raises tool usage) |
| Losing the thread after compaction ([#13112](https://github.com/anthropics/claude-code/issues/13112) and 4+ open feature requests) | **Deterministic compaction recovery** — a PreCompact hook saves the original request verbatim; the SessionStart(compact) hook injects it back plus the actual git state |
| Plausible-but-wrong conclusions surviving | `/verify-claim` (3 refuters, distinct lenses, fail-closed vote) and `/paranoid-review` (coverage-first finders → adversarial verifiers) |
| Review filters silently dropping findings (Anthropic prompting guide) | Coverage-first finder prompts + **three-way verdicts** (confirmed / refuted / unverified — nothing silently dropped) |
| Grinding in overthinking/fix loops | Observable loop-detection rule + `oracle` escalation + **deterministic loop-alarm hook** (3rd identical failing command with no file change in between → forced stop-and-reassess) |
| Weakening tests to force a green run (reward hacking) | Doctrine rule + **test-weakening alarm hook** (deterministic; fires the moment a skip/disable marker is added to a test file) + the claim-audit gate calls it out whenever test files were edited under a completion claim |
| Destroying uncommitted work with reflexive `reset --hard`/`checkout --` | **Destructive-command guard hook** — blocks unrecoverable ops when work would be lost; user-approved override only |
| Sycophancy undermining review | Anti-sycophancy calibration rules |

The one knob that matters: on Opus 4.8, `effortLevel: "xhigh"` is THE lever (Anthropic: "more important for this model than any prior Opus"). The folklore knobs — `MAX_THINKING_TOKENS`, `alwaysThinkingEnabled` — are **inert** on adaptive-thinking models. Everything else has to be structural. That's this kit.

Full research with sources: [docs/RESEARCH.md](docs/RESEARCH.md).

## What's inside

```
claude/
  CLAUDE.md                    global doctrine (~40 lines — lean by design)
  agents/
    verifier.md                adversarial post-implementation audit (fresh context, xhigh)
    plan-critic.md             attacks plans before code exists (xhigh)
    oracle.md                  max-effort consultant for stuck problems
  workflows/                   become /commands in Claude Code (≥2.1.154)
    paranoid-review.js         4 finder dimensions → adversarial verify per finding
    verify-claim.js            3 independent refuters + fail-closed majority vote
    deep-plan.js               3 competing planners → 3 judges → synthesis
    bug-hunt.js                loop-until-dry sweep, rotating lenses, budget-guarded
  skills/
    fable/                     the flagship: full staged protocol for hard tasks (/fable)
    orchestrate/               multi-agent workflow authoring playbook
    postmortem/                distill lessons into persistent memory
  hooks/
    stop-claim-audit.py        blocks the first "done/verified" stop after file edits
                               (Edit/Write or file-writing Bash), forces one audit pass
                               (exit-2 protocol — JSON block is broken in -p mode, see
                               bench/RESULTS.md); flags possible test-weakening when test
                               files were edited; negation-aware, fails open, unit-tested
    posttool-loop-alarm.py     deterministic grind detector: the same command failing 3x
                               with no file modification in between gets a one-time
                               stop-and-reassess injection (route to oracle)
    posttool-test-weakening-alarm.py  fires the moment an Edit/Write ADDS a skip/disable
                               marker (@pytest.mark.skip, it.skip, t.Skip, #[ignore],
                               @Disabled, ...) to a test file — once per file; demands a
                               revert-or-justify in the final message
    pretool-destructive-guard.py blocks reset --hard / checkout -- / restore / clean -f
                               when uncommitted work would be lost; stash drop|clear,
                               bare force-push, catastrophic rm -rf always; override
                               requires explicit user approval (FABLE_DESTRUCTIVE_OK=1)
    precompact-save-task.py    saves the original user request verbatim before every
                               compaction (per-session state file)
    sessionstart-compact-recovery.py  post-compaction injection: recovery protocol +
                               the saved original request + the ACTUAL git state
  settings/settings-snippet.json   effortLevel xhigh + all six hooks wired to their events
install.sh                     copies into ~/.claude with out-of-tree backups; idempotent;
                               never edits settings
bench/                         A/B harness proving the kit beats stock Opus 4.8 (RESULTS.md)
tests/                         unit tests for hooks, installer+doctor, snippet sync (CI)
tools/check-workflows.mjs      syntax-checks the workflow scripts (CI)
tools/doctor.sh                post-install verifier: every component present, every hook
                               actually wired in settings.json — catches the silently-inert
                               install (botched settings merge) deterministically
```

## Measured, not vibes

The kit ships its own benchmark (`bench/`): a planted-bug task targeting the documented
failure modes, run headless as stock Opus 4.8 vs Opus 4.8 + this kit, scored by a hidden
acceptance suite. Headline from [bench/RESULTS.md](bench/RESULTS.md): stock and doctrine-only
runs both produced **false "all verified" claims** over a red test suite (the exact failure
mode from #63861, reproduced on demand); with the claim-audit gate, **4/4 runs scored 15/15
with zero false claims**, and in one run the transcript shows the gate directly rescuing a
would-be false claim — the model tried to stop, got blocked, ran the check it had skipped,
and fixed the bug it had shipped. Small n, honest stats in the file.

## Install

```bash
git clone https://github.com/blyatiful1/fable-protocol
cd fable-protocol && ./install.sh
```

Then merge the printed snippet into `~/.claude/settings.json` and fill in the `## This machine` section of `~/.claude/CLAUDE.md`. Requires Claude Code ≥ 2.1.154 (saved workflows).

Then **verify the install deterministically** — the settings merge is the one manual step, and a botched merge leaves every hook silently unwired:

```bash
./tools/doctor.sh
```

Finally, confirm the doctrine load in a fresh session: *"quote the first bullet of your Evidence before claims doctrine."*

## Usage playbook

| Situation | Reach for |
|---|---|
| Hard / multi-part / high-stakes task | `/fable` — the full staged protocol |
| Open-ended strategy, unfamiliar codebase | `/deep-plan <task>` then `plan-critic` |
| About to report multi-file work as done | `verifier` agent (auto-delegates) |
| Merging a substantive diff | `/paranoid-review` |
| Acting on a diagnosis / root cause / external fact | `/verify-claim <claim>` |
| Latent bugs in existing code | `/bug-hunt [scope]` |
| Bug survives two fix attempts | `oracle` agent |
| Work one context can't hold | `orchestrate` skill |
| End of a debugging saga | `postmortem` skill |

## Design principles (what this kit refuses to do)

- **Lean over kitchen-sink.** The doctrine is ~50 lines. Popular frameworks eager-load personas and burn context ("every instruction in your CLAUDE.md eats context window" is the top complaint about them). Advisory rules live in CLAUDE.md; rules that MUST hold live in hooks — the benchmark caught the doctrine being skipped under momentum (hyper-2) and the hook not being skippable (4/4).
- **Stakes-matched depth.** Every component has an explicit "when NOT to use me" — the doctrine's effort floor sends trivial questions straight to answers. Multi-agent ceremony on small tasks is waste, not rigor (the loudest complaint about methodology frameworks).
- **Adversarial, not cooperative, verification.** Reviewers that try to *refute* findings, refuters that default to "unproven ≠ disproven", judges with distinct lenses. Cooperative review ("does it look right?") is how false-greens survive.
- **Three-way honesty.** Confirmed / refuted / unverified. A dead subagent is not a passing check; an unprovable claim is not a disproven one.

## Recommended companions (not bundled — third-party)

Curated from the ecosystem; each earns its permanent context cost. Install with [`npx skills`](https://skills.sh):

```bash
npx skills add obra/superpowers --skill systematic-debugging -g -a claude-code -y   # diagnosis discipline upstream of verification
npx skills add mattpocock/skills --skill tdd -g -a claude-code -y                   # lean red-green-refactor
npx skills add trailofbits/skills --skill differential-review -g -a claude-code -y  # audit-firm security diff methodology
npx skills add obra/superpowers --skill brainstorming -g -a claude-code -y          # Socratic design refinement — see note
npx skills add juliusbrussee/caveman --skill caveman-commit -g -a claude-code -y    # terse Conventional Commits
```

> **Note on brainstorming:** its stock description auto-triggers on *any* feature work. Edit the `description:` in its SKILL.md to "invoke deliberately for big/ambiguous features only", or it becomes ceremony on every small task.

## Cost honesty

`xhigh` effort plus multi-agent verification is real money and real minutes — that is the trade: you buy Fable-grade reliability with Opus-grade tokens (still ~half Fable's price per token). The workflows are budget-guarded and the doctrine downshifts on trivial work, but don't run `/paranoid-review` on a typo fix. When a run fans out, the kit tells you what it spent.

## On models after Opus 4.8

The kit targets **failure modes, not model IDs** — nothing in it hardcodes `claude-opus-4-8`. When your subscription's default model changes (an Opus 4.9/5, a Sonnet that inherits the agentic crown, or Mythos-class access), the failure-mode table above is the checklist to re-run, and three assumptions are the ones most likely to break:

1. **`effortLevel: "xhigh"` semantics.** On Opus 4.8 it is THE lever; a successor may rename the levels, change the default, or recalibrate what xhigh buys. Check the model's migration guide before assuming the snippet's value is still optimal — an effort knob left at the wrong tier is either wasted spend or a silent downgrade.
2. **Hook payload contracts.** The loop alarm keys off explicit exit codes in `tool_response`; the claim-audit gate reads `last_assistant_message` and the transcript JSONL shape; blocking relies on the exit-2 + stderr protocol. All three are Claude Code contracts, not model contracts, but they drift with CLI versions — after any major update, re-run `./tools/doctor.sh` and the one-minute live checks in Known limits.
3. **Which failure modes still exist.** The deterministic layer (hooks) is cheap insurance on any model — a stronger model just trips it less. The *ceremony* layer (multi-agent review, staged protocol) is where to downshift first: if a successor model stops producing false completion claims on the bench task, `bench/` will show it (rerun is one command), and you can retire the corresponding ceremony instead of paying for rigor the model no longer needs.

The bench harness is the kit's own succession plan: measure the new model stock vs kitted, keep what still earns its cost, drop what doesn't.

Going the other direction — running the kit on a **smaller** driver model (a Sonnet or Haiku daily driver) — is covered by [docs/SUCCESSION.md](docs/SUCCESSION.md): what breaks first as the model shrinks, the config deltas (`FABLE_LOOP_THRESHOLD=2`, pinning the verification agents to the strongest tier your plan offers), and the asymmetric-verification principle (draft cheap, verify strong; when all tiers are small, buy rigor with votes instead of weights).

## Known limits

- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000` is best-effort: harmless (clamped per model), but whether it raises the effective cap is **unverified** — the kit's own doctrine requires saying so.
- The loop-alarm hook counts a run as *failed* only when the PostToolUse payload carries an explicit exit code / error flag. If your Claude Code version omits exit information from Bash `tool_response`, the alarm is silently inert (fail-open by design) — verify once with a deliberately failing command repeated 3×.
- The test-weakening alarm reads Edit/Write payloads, so a skip marker smuggled in via a Bash heredoc doesn't trip it at edit time — but the claim-audit gate now flags any file-writing Bash command that names a test path, so the stop-time audit still fires.
- No prompt kit closes the gap on the longest-horizon work (multi-hour autonomous runs); route those to a stronger model when available.
- Built for Claude Code 2.1.x in mid-2026; contracts (workflow API, hook events, frontmatter) may drift. The kit was verified live on `claude-opus-4-8` + Claude Code 2.1.198 on 2026-07-02.

## Provenance & credits

Researched, written, adversarially self-reviewed, and live-verified by **Claude Fable 5** (with its human, [@blyatiful1](https://github.com/blyatiful1)) as its own succession plan. Prior art that informed the design: Anthropic's [Opus 4.8 migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide) and [Claude Code best practices](https://code.claude.com/docs/en/best-practices), [obra/superpowers](https://github.com/obra/superpowers), [fivetaku/fablize](https://github.com/fivetaku/fablize), [trailofbits/skills](https://github.com/trailofbits/skills), [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery).

MIT — see [LICENSE](LICENSE).

*"Feeling confident is not evidence." — the fable skill, Stage 0*
