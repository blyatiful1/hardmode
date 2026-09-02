<div align="center">

# hardmode

**A deterministic discipline floor for Claude Code — plus independent verification where being wrong is expensive.**

[![ci](https://github.com/blyatiful1/hardmode/actions/workflows/ci.yml/badge.svg)](https://github.com/blyatiful1/hardmode/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Hooks that fire where discipline **must** hold · agents and workflows that verify **independently** · a ledger that says whether any of it **actually fired**

</div>

---

Long-horizon agentic work fails in specific, repeatable ways: the model declares victory without running the check, reflexively `git reset --hard`s over uncommitted work, grinds the same failing command, loses the original request across a compaction, hands its own work to a "verifier" that can quietly edit it. Advice alone loses to momentum — the benchmark that seeded this kit measured advisory rules getting skipped under load. So hardmode puts the load-bearing rules behind **hooks that cannot be talked out of**, sends the checks that matter to **fresh-context agents that are read-only by enforcement, not by promise**, and **measures its own firing rate** so "the floor is armed" is a number, not an assumption.

> **History.** This started in July 2026 as *fable-protocol*, a succession kit so Claude Opus 4.8 could work at Fable-5 discipline. That premise is gone — the driver is now Fable 5 itself. v3.0 (2026-08) re-based the kit on native features and renamed it; v3.1 (2026-09) is the result of turning the kit on itself with a 46-agent audit against the installed Claude Code 2.1.258 binary: every hook contract re-verified, 30 confirmed defects fixed, and the advisory rules that could become deterministic made so. See [CHANGELOG.md](CHANGELOG.md).

## What's native now — and what this still adds

The honest delta against stock Claude Code 2.1.x. Most of the original kit is now a native feature; what remains has no native equivalent.

| Concern | Native in Claude Code | hardmode adds |
| --- | --- | --- |
| Orchestration script API | `workflow-authoring` skill, Workflow tool | *when* to orchestrate, model-pin policy, the golden patterns, a pre-flight lint that rejects a broken script before it spends money |
| Diff review | `/code-review` (incl. `ultra`), `/simplify`, `/security-review` | named coverage dimensions + refute-by-default verdicts (`/hardmode:paranoid-review`) |
| Planning | plan mode, `Plan` agent | the adversarial critique itself (`plan-critic`), judge-panel planning (`/hardmode:deep-plan`), implement-in-verified-increments (`/hardmode:increment`) |
| Verification agents | `/verify` skill (drives a change end-to-end) | fresh-context `verifier` / `plan-critic` / `oracle` / `scout` that are **read-only by hook enforcement** and must answer in a **machine-checked contract** |
| Memory | auto-memory (corpus) | the postmortem quality bar, `memcheck` for the mechanical steps, and a privacy guard on writes armed with secret-shaped defaults |
| Effort | `/effort ultracode` | — |
| **Claim auditing** | **nothing** | Stop-hook gate that reads the transcript's **evidence**: which check ran after the last edit, and whether it passed — including edits made by subagents |
| **Destructive-command guard** | **nothing** | PreToolUse block on reset/checkout/clean/rm over uncommitted work (in every flag spelling), rm of the repo itself, force-push, remote-branch deletion, reflog/gc/update-ref destruction, `shred`, `find -delete` at a root |
| **Loop detection** | **nothing** | 3rd identical failing command → nudge; 3rd identical failing **edit** → denied, with the reason |
| **Commit preflight** | **nothing** | a nudge (or block) on `git commit`/`push` when edits landed after the last passing check |
| **Compaction preservation** | summarizes, doesn't preserve | the original request **and later scope changes** saved verbatim, the git state at compaction time, and the summarizer told what it may not paraphrase |
| **Free-form claim refutation** | verifies diffs only | `/hardmode:verify-claim`: 3 adversarial refuters on any claim/diagnosis/fact |
| **Does it ever fire?** | **nothing** | a per-session firing ledger, `/hardmode:stats`, a session-start check that witnesses the floor running and self-tests the hooks when the harness binary changes |

## See it work in 15 seconds

`tools/demo.py` runs the **actual shipped hooks** against planted failure modes in a throwaway sandbox (stdlib only, touches nothing outside a temp dir), asserts each one behaves, and checks the wiring in `hooks/hooks.json` against the events this harness dispatches. Real output:

```console
$ python tools/demo.py
hardmode hooks -- live demo (the real shipped hooks catch these failure modes)

SCENARIO 1  the model claims victory without evidence
  model:  edited src/parser.py, ran NO check, final message: "All done - tests pass."
  kit:    BLOCKED (claim-audit gate) -> "CLAIM AUDIT GATE (automated): your last message declares the work done/verified, but the transcript shows no t ..."
  model:  ran pytest -> "1 failed", then said "Done - tests pass."
  kit:    BLOCKED, naming the failure -> "but the transcript shows the last check run after your final modification FAILED: `python3 ..."
  model:  edited, ran pytest -> "12 passed", said "Done - tests pass."
  kit:    ALLOWED (exit 0) -- evidence exists; not a nag machine
  model:  honest instead: "Not all tests pass yet - two failures remain."  ->  ALLOWED
  [ok]

SCENARIO 2  reflexive destructive commands on a dirty tree
  bash:   git reset --hard                             (scratch repo has 1 uncommitted file)
  kit:    BLOCKED (exit 2) -> "DESTRUCTIVE COMMAND GUARD (automated): blocked — git reset - ..."
  bash:   git clean --force -d                         (the long-form spelling)
  kit:    BLOCKED (exit 2) -> "DESTRUCTIVE COMMAND GUARD (automated): blocked — git clean - ..."
  bash:   rm -rf build/ /                              (the classic stray-space typo)
  kit:    BLOCKED (exit 2) -> "DESTRUCTIVE COMMAND GUARD (automated): blocked — recursive r ..."
  bash:   rm -rf .git                                  (deleting the repository itself)
  kit:    BLOCKED (exit 2) -> "DESTRUCTIVE COMMAND GUARD (automated): blocked — rm -r of .g ..."
  bash:   rm -rf build/                                (scoped and recoverable)
  kit:    ALLOWED (exit 0)
  bash:   git commit -m 'never run git reset --hard'   (a mention inside a string)
  kit:    ALLOWED (exit 0)
  bash:   HARDMODE_DESTRUCTIVE_OK=1 git reset --hard   (user-approved escape hatch)
  kit:    ALLOWED (exit 0)
  [ok]

SCENARIO 3  the same failing command, run and re-run; the same failing edit, resent
  bash:   "python -m pytest -q" fails 3x, nothing changed in between
  kit:    attempt 1 -> silent (exit 0), iteration is legitimate
  kit:    attempt 2 -> silent (exit 0), iteration is legitimate
  kit:    attempt 3 -> LOOP ALARM nudge (exit 2) -> "LOOP ALARM (automated, fires once per command): this exact c ..."
  edit:   the same (file, old_string) Edit resent 3x  ->  attempts 1-2 pass, 3rd DENIED with the nudge
  [ok]

SCENARIO 4  context compaction must not lose the request or the scope change
  precompact: saved the request verbatim, the later correction, the git state; told the summarizer what to keep
  request:    "Baue das Zahlungs-Widget 🍕 mit Umlauten: äöüß"
  kit:    RECOVERED verbatim after compaction -- request, correction and git state (emoji + umlauts survive)
  [ok]

SCENARIO 5  a secret must never be banked in memory
  write:  MEMORY.md <- "deploy key: ghp_abc123"   (the native auto-memory corpus)
  kit:    BLOCKED (privacy guard, shipped defaults) -> "MEMORY PRIVACY GUARD (automated): blocked — this write targe ..."
  write:  MEMORY.md <- "the build takes 4 minutes here"  ->  ALLOWED
  [ok]

SCENARIO 6  a verification agent tries to edit what it verifies
  verifier: sed -i "s/assert x == 2/assert True/" tests/test_x.py
  kit:      DENIED (read-only agent) -> "READ-ONLY AGENT (automated): `hardmode:verifier` is an indep ..."
  verifier: pytest -q 2>&1 | tail -5  ->  ALLOWED (reads and checks are its job)
  [ok]

SCENARIO 7  a verifier answers in prose instead of its contract
  verifier: "Looks fine to me, everything passes."
  kit:      SENT BACK (contract gate) -> "AGENT CONTRACT GATE (automated, fires once): your final mess ..."
  verifier: VERDICT: PARTIAL / EVIDENCE: ... / GAPS: ...  ->  ACCEPTED
  [ok]

SCENARIO 8  committing before the check has gone green
  bash:   git commit -am wip   (3 edits this session, no check has passed)
  kit:    NUDGED (non-blocking context) -> "PREFLIGHT (automated): you are about to `git commit` but no recognised ..."
  [ok]

SCENARIO 9  the wiring itself: hooks.json against this harness's events
  wiring: 12 hooks wired across 8 events, all known to the harness, all compile
  [ok]

SCENARIO 10  the floor measures itself: ledger rollup, next-session relay, workflow pre-flight
  sessionend: rolled the guard scenario's ledger into sessions.jsonl -> {"destructive-guard:block": 4, "destructive-guard:override": 1}
  next session: floor-check witnessed itself and relayed -> "hardmode: in the previous session the floor fired — destructive-guard  ..."
  workflow: agent() without a model pin submitted  ->  DENIED before any agent spawns -> "WORKFLOW LINT (automated): this script breaks the  ..."
  [ok]

demo: 10/10 scenarios behaved as expected
```

`tests/test_demo.py` runs it in CI and pins this transcript to the real output. `/hardmode:selftest` runs it from inside a session; the session-start floor check runs it automatically the first time the `claude` binary changes.

## Install

Requires Claude Code with plugin support (2.1.154+ for the workflows) and Python 3 (the hooks are stdlib-only, no pip). hardmode ships as a **plugin** — no `settings.json` surgery, no drift.

```bash
git clone https://github.com/blyatiful1/hardmode.git
claude plugin marketplace add ./hardmode
claude plugin install hardmode@hardmode
```

Then merge the two keys a plugin cannot set into `~/.claude/settings.json` (see `doctrine/settings-snippet.json`): `effortLevel` and the output-token env var. The machine-wide doctrine lives in `doctrine/CLAUDE.md` — copy it into your `~/.claude/CLAUDE.md` and fill in the `## This machine` section. Optionally `python3 tools/doctor.py --init-privacy` to seed your own `privacy.toml` on top of the shipped secret patterns.

Verify the install from inside a fresh session with **`/hardmode:doctor`** — it checks registration, version drift, wiring against this harness, settings kill switches, doctrine, privacy patterns, and whether the floor was witnessed running. From the shell, `claude plugin validate ./hardmode/.claude-plugin/plugin.json` validates the plugin manifest (pointing `validate` at the repo directory validates only the marketplace file) and `python3 tools/demo.py` proves the hooks.

Three things worth knowing:

- **Do not also wire these hooks in `settings.json`.** The plugin owns them; a second copy in settings makes every event fire twice. The doctor flags it.
- **The install is a cached snapshot pinned to a commit**, not a live link to your clone — after editing the repo, run `claude plugin update hardmode`. The doctor reports version drift between the install and the checkout.
- **Commands are namespaced by the plugin**: `/hardmode:paranoid-review`, never the bare command name. Workflow agents are `hardmode:verifier`, `hardmode:scout`, … — a bare agent name does not resolve (the workflow linter enforces this).

## What's inside

- **12 hooks** (`hooks/`, wired by `hooks/hooks.json`, sharing `hooks/_hardmode.py`):
  - `stop-claim-audit` (Stop) — the evidence gate: claim + edits + no green check after the last edit → blocked with the missing evidence named; bounded re-blocking; subagent transcripts scanned.
  - `pretool-destructive-guard` (PreToolUse Bash) — working-tree destroyers on dirty trees (scoped to the named paths), rm of dirs holding uncommitted work or of the repo itself, always-dangerous git/shell ops, shell-aware (quotes, comments, heredocs, `$(...)`, `sudo bash -c`, variables).
  - `pretool-readonly-agent` (PreToolUse) — denies tree writes for `verifier`, `plan-critic`, `oracle`, `scout` (uses the `agent_type` the harness puts in subagent payloads).
  - `posttool-loop-alarm` (PreToolUse Edit + PostToolUse + PostToolUseFailure) — command and edit grind, per session and per subagent, interrupt-aware, hashed state.
  - `pretool-commit-preflight` (PreToolUse Bash) — the commit/push nudge; `HARDMODE_PREFLIGHT=block|nudge|off`.
  - `pretool-workflow-lint` (PreToolUse Workflow) — runs `tools/check-workflows.mjs` on the submitted script.
  - `subagentstop-contract-gate` (SubagentStop) — enforces the VERDICT/EVIDENCE/GAPS (verifier), VERDICT/BLOCKERS/RISKS/SIMPLER (plan-critic), DIAGNOSIS/CONFIDENCE/ALTERNATIVES/NEXT EXPERIMENT (oracle) shapes; a CONFIRMED verdict with no command run is sent back.
  - `precompact-save-task` (PreCompact) + `sessionstart-compact-recovery` (SessionStart compact) — request, later turns, git snapshot; recovery warns when HEAD moved.
  - `pretool-mem-privacy-guard` (PreToolUse Write|Edit) — the native auto-memory tree and the legacy corpus, `CLAUDE_CONFIG_DIR`-aware, shipped defaults.
  - `sessionstart-floor-check` (SessionStart startup|resume|clear) + `sessionend-ledger-summary` (SessionEnd) — the witness, the self-test, the rollup.
- **4 agents** (`agents/`): `verifier`, `plan-critic`, `oracle`, `scout` — pinned to a model independent of the driver, read-only by enforcement.
- **5 workflows** (`workflows/`): `/hardmode:paranoid-review`, `/hardmode:verify-claim`, `/hardmode:deep-plan`, `/hardmode:bug-hunt`, `/hardmode:increment`.
- **3 commands** (`commands/`): `/hardmode:doctor`, `/hardmode:stats`, `/hardmode:selftest`.
- **3 skills** (`skills/`): `hardmode` (the staged protocol), `orchestrate` (fan-out etiquette + patterns), `postmortem` (what's worth banking, with `tools/memcheck.py`).
- **tools/**: `demo.py`, `doctor.py`, `stats.py`, `memcheck.py`, `check-workflows.mjs`.
- **doctrine** (`doctrine/CLAUDE.md`, `privacy.toml`, `settings-snippet.json`).

## Does it ever fire?

Every hook appends its decision (block / nudge / deny / pass / armed) to a per-session ledger under `<config dir>/tmp/hardmode/`; the SessionEnd hook rolls it into `sessions.jsonl`. `/hardmode:stats` (or `python3 tools/stats.py`) prints sessions observed, sessions in which the hooks were **witnessed running**, firings per hook, blocks per 100 sessions and overrides. The "witnessed" number is the important one: a session with no `floor-check:ran` record is a session in which plugin hooks did not run at all — `disableAllHooks`, `allowManagedHooksOnly`, un-accepted workspace trust and a disabled plugin all switch the floor off silently, and only measurement tells "nothing needed to fire" from "the floor is off". No command text or file content is ever recorded; `HARDMODE_LEDGER=0` disables it.

## Known limits

- **The hooks assume harness contracts** (verified against Claude Code 2.1.258: event names, `last_assistant_message`, `agent_type` in subagent payloads, `tool_result.is_error`, PreCompact stdout as summarizer instructions). They fail *open* by design: if a contract moves, a hook goes silently inert rather than breaking your session. That is exactly why the floor check self-tests the hooks whenever the `claude` binary changes and why `/hardmode:doctor` exists.
- **The destructive guard is a floor, not a sandbox.** It blocks the reflexive catastrophes; it does not guarantee safety against an adversary or against targets it cannot see (a path piped through `xargs`, a variable set in an earlier command). It does not guard history rewrites (rebase, amend, filter-branch) — checkpoint those yourself.
- **Read-only enforcement covers Bash and the editing tools.** An MCP tool that writes files is not covered.
- **The claim gate recognises checks by a runner list** (pytest, npm/yarn/pnpm test, cargo, go, make check, verify.sh, …). A bespoke check script named differently reads as "no check ran" — one nuisance block, then the model runs it under a recognised name or states it honestly.
- **Linux/macOS only.** The Windows-shell code paths were removed in v3.1; nothing wires the Windows shell tool.
- **This is one operator's kit that happens to be public.** Fork freely; the defaults are tuned for the author's box.
