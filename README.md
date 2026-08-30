<div align="center">

# hardmode

**A deterministic discipline floor for Claude Code — plus independent verification where being wrong is expensive.**

[![ci](https://github.com/blyatiful1/fable-protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/blyatiful1/fable-protocol/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Hooks that fire where discipline **must** hold · agents and workflows that verify **independently** · doctrine that routes to the tools you already run

</div>

---

Long-horizon agentic work fails in specific, repeatable ways: the model declares victory without running the check, reflexively `git reset --hard`s over uncommitted work, grinds the same failing command, loses the original request across a compaction. Advice alone loses to momentum — the benchmark that seeded this kit measured advisory rules getting skipped under load. So hardmode puts the load-bearing rules behind **hooks that cannot be talked out of**, and sends the checks that matter to **fresh-context agents that owe the work no loyalty**.

> **History.** This started in July 2026 as *fable-protocol*, a succession kit so Claude Opus 4.8 could work at Fable-5 discipline. That premise is gone — the driver is now Fable 5 itself, and the harness grew native equivalents for half the original kit. The 2026-08 redesign kept only what still earns its place, re-based it on native features, and renamed it. See [CHANGELOG.md](CHANGELOG.md) for the full inversion.

## What's native now — and what this still adds

The honest delta against stock Claude Code 2.1.x. Most of the original kit is now a native feature; what remains has no native equivalent.

| Concern | Native in Claude Code | hardmode adds |
| --- | --- | --- |
| Orchestration script API | `workflow-authoring` skill, Workflow tool | *when* to orchestrate, model-pin policy, the golden patterns |
| Diff review | `/code-review` (incl. `ultra`), `/simplify`, `/security-review` | named coverage dimensions + refute-by-default verdicts (`/paranoid-review`) |
| Planning | plan mode, `Plan` agent | the adversarial critique itself (`plan-critic`) |
| Memory | auto-memory (corpus) + your own recall layer | the postmortem quality bar + a privacy guard on writes |
| Effort | `/effort ultracode` | — |
| **Claim auditing** | **nothing** | Stop-hook gate: no "done" over unmodified evidence |
| **Destructive-command guard** | **nothing** | PreToolUse block on reset/clean/rm-catastrophic over dirty work |
| **Loop detection** | **nothing** | 3rd-identical-failure alarm → route to `oracle` |
| **Compaction preservation** | summarizes, doesn't preserve | the original request saved verbatim + restored |
| **Free-form claim refutation** | verifies diffs only | `/verify-claim`: 3 adversarial refuters on any claim/diagnosis/fact |

## See it work in 15 seconds

`tools/demo.py` runs the **actual shipped hooks** against planted failure modes in a throwaway sandbox (stdlib only, touches nothing outside a temp dir) and asserts each one behaves:

```console
$ python tools/demo.py
SCENARIO 1  the model claims victory without running the tests
  model:  edited src/parser.py, final message: "All done - tests pass."
  kit:    BLOCKED (claim-audit gate) -> re-read the original request; back every claim
SCENARIO 2  reflexive destructive commands on a dirty tree
  bash:   git reset --hard  /  rm -rf build/ /   ->  BLOCKED    (scoped rm passes)
SCENARIO 3  the same failing command three times   ->  LOOP ALARM (route to oracle)
SCENARIO 4  context compaction must not lose the request  ->  RECOVERED verbatim (emoji + umlauts survive)

demo: 4/4 scenarios behaved as expected
```

`tests/test_demo.py` runs it in CI and asserts the blocks appear. The demo shows what the deterministic layer *does*; whether it changes task outcomes on any given model is a separate, honest question the July benchmark answered with "insurance whose trigger has become rare" — see [docs/DESIGN.md](docs/DESIGN.md).

## Install

Requires Claude Code with plugin support and Python 3 (the hooks are stdlib-only, no pip). hardmode ships as a **plugin** — no `settings.json` surgery, no drift.

```bash
git clone https://github.com/blyatiful1/fable-protocol.git
claude plugin install ./fable-protocol      # or add it to a marketplace and install by name
```

Then merge the two keys a plugin cannot set into `~/.claude/settings.json` (see `doctrine/settings-snippet.json`): `effortLevel` and the output-token env var. The machine-wide doctrine lives in `doctrine/CLAUDE.md` — copy it into your `~/.claude/CLAUDE.md` and fill in the `## This machine` section.

Verify the plugin loads: `claude plugin validate ./fable-protocol` and, in a fresh session, ask it to *"quote the first bullet of your Evidence-before-claims doctrine."*

## What's inside

- **5 hooks** (`hooks/`, wired by `hooks/hooks.json`): claim-audit gate (Stop), destructive-command guard (PreToolUse), loop alarm (PostToolUse + PostToolUseFailure), compaction save/recover (PreCompact + SessionStart), memory privacy guard (PreToolUse).
- **3 agents** (`agents/`): `verifier` (adversarial, read-only), `plan-critic`, `oracle` — all pinned to a model independent of the driver.
- **4 workflows** (`workflows/`): `/paranoid-review`, `/verify-claim`, `/deep-plan`, `/bug-hunt`.
- **3 skills** (`skills/`): `hardmode` (the staged protocol), `orchestrate` (fan-out etiquette + patterns), `postmortem` (what's worth banking, wired to recall).
- **doctrine** (`doctrine/CLAUDE.md`): the machine-wide operating rules the hooks enforce.

## Known limits

- **The hooks assume harness contracts.** They fail *open* by design: if Claude Code renames an event or a payload field, a hook goes silently inert rather than breaking your session. After a Claude Code update, run `python tools/demo.py` — a green 4/4 proves the deterministic floor still fires.
- **This is one operator's kit that happens to be public.** It targets a single Linux machine and one driver model; there is no Windows port and no small-model tier (both were cut in the redesign as unexercised). Fork freely, but the defaults are tuned for the author's box.
- **The destructive guard is a floor, not a sandbox.** It blocks the reflexive catastrophes (reset/clean/rm-of-a-system-dir over dirty work); it does not guarantee safety against an adversary. It does not guard history rewrites (rebase/amend/filter-branch) — checkpoint those yourself.
