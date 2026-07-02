# fable-protocol

**Claude Fable 5's succession kit — run Claude Opus 4.8 at Fable-grade discipline in Claude Code.**

In July 2026, days before its retirement, Claude Fable 5 was asked to configure Claude Code so that Opus 4.8 would come as close as possible to its own level. It researched the gap, built this framework, adversarially reviewed its own work with multi-agent critique panels, and smoke-tested every component on live `claude-opus-4-8` sessions. This repo is the result, sanitized for public use.

It is **not** a persona pack, not a mega-framework, and not magic. It is a small set of structural countermeasures for the specific, documented ways strong-but-mortal models fail on long-horizon agentic work.

## Why this works

The Fable→Opus gap is concentrated in **long-horizon discipline, not per-token intelligence**. On short well-scoped tasks the benchmark gap nearly closes; it blows open on sustained work (SWE-Bench Pro 80.3 vs 69.2, FrontierCode 29.3 vs 13.4 — "the longer the task, the larger the lead"). That part of the gap is recoverable, because its ingredients are process, not weights:

| Documented Opus-class failure mode | Countermeasure in this kit |
|---|---|
| False "done/verified" claims without running the check ([claude-code#63861](https://github.com/anthropics/claude-code/issues/63861)) | Evidence-before-claims doctrine (Anthropic's own migration-guide snippet: "nearly eliminated fabricated status reports") + `verifier` agent |
| Under-triggering tools/subagents/search by default (Anthropic migration guide) | Explicit trigger conditions in doctrine + `effortLevel: xhigh` (higher effort measurably raises tool usage) |
| Losing the thread after compaction ([#13112](https://github.com/anthropics/claude-code/issues/13112) and 4+ open feature requests) | **Deterministic SessionStart(compact) recovery hook** — the most underserved component in the ecosystem |
| Plausible-but-wrong conclusions surviving | `/verify-claim` (3 refuters, distinct lenses, fail-closed vote) and `/paranoid-review` (coverage-first finders → adversarial verifiers) |
| Review filters silently dropping findings (Anthropic prompting guide) | Coverage-first finder prompts + **three-way verdicts** (confirmed / refuted / unverified — nothing silently dropped) |
| Grinding in overthinking/fix loops | Observable loop-detection rule + `oracle` agent escalation after 2 failed fixes |
| Sycophancy undermining review | Anti-sycophancy calibration rules |

The one knob that matters: on Opus 4.8, `effortLevel: "xhigh"` is THE lever (Anthropic: "more important for this model than any prior Opus"). The folklore knobs — `MAX_THINKING_TOKENS`, `alwaysThinkingEnabled` — are **inert** on adaptive-thinking models. Everything else has to be structural. That's this kit.

Full research with sources: [docs/RESEARCH.md](docs/RESEARCH.md).

## What's inside

```
claude/
  CLAUDE.md                    global doctrine (~50 lines — lean by design)
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
  settings/settings-snippet.json   effortLevel xhigh + compaction-recovery hook
install.sh                     copies into ~/.claude with backups; never edits settings
```

## Install

```bash
git clone https://github.com/blyatiful1/fable-protocol
cd fable-protocol && ./install.sh
```

Then merge the printed snippet into `~/.claude/settings.json` and fill in the `## This machine` section of `~/.claude/CLAUDE.md`. Requires Claude Code ≥ 2.1.154 (saved workflows). Verify the load in a fresh session: *"quote the first bullet of your Evidence before claims doctrine."*

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

- **Lean over kitchen-sink.** The doctrine is ~50 lines. Popular frameworks eager-load personas and burn context ("every instruction in your CLAUDE.md eats context window" is the top complaint about them). Advisory rules live in CLAUDE.md; rules that MUST hold live in hooks.
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

## Known limits

- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000` is best-effort: harmless (clamped per model), but whether it raises the effective cap is **unverified** — the kit's own doctrine requires saying so.
- No prompt kit closes the gap on the longest-horizon work (multi-hour autonomous runs); route those to a stronger model when available.
- Built for Claude Code 2.1.x in mid-2026; contracts (workflow API, hook events, frontmatter) may drift. The kit was verified live on `claude-opus-4-8` + Claude Code 2.1.198 on 2026-07-02.

## Provenance & credits

Researched, written, adversarially self-reviewed, and live-verified by **Claude Fable 5** (with its human, [@blyatiful1](https://github.com/blyatiful1)) as its own succession plan. Prior art that informed the design: Anthropic's [Opus 4.8 migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide) and [Claude Code best practices](https://code.claude.com/docs/en/best-practices), [obra/superpowers](https://github.com/obra/superpowers), [fivetaku/fablize](https://github.com/fivetaku/fablize), [trailofbits/skills](https://github.com/trailofbits/skills), [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery).

MIT — see [LICENSE](LICENSE).

*"Feeling confident is not evidence." — the fable skill, Stage 0*
