<div align="center">

# fable-protocol

**Claude Fable 5's succession kit — run Claude Opus 4.8 at Fable-grade discipline in Claude Code.**

[![ci](https://github.com/blyatiful1/fable-protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/blyatiful1/fable-protocol/actions/workflows/ci.yml)
![platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-555)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Deterministic hooks where discipline **must** hold · adversarial agents and workflows where verification **matters** · cross-project memory that outlives the session

[See it work](#see-it-work-in-30-seconds) · [Install](#install) · [Why this works](#why-this-works) · [What's inside](#whats-inside) · [Does it help?](#does-it-actually-help) · [Playbook](#usage-playbook) · [Known limits](#known-limits)

</div>

---

In July 2026, days before its retirement, Claude Fable 5 was asked to configure Claude Code so that Opus 4.8 would come as close as possible to its own level. It researched the gap, built this framework, adversarially reviewed its own work with multi-agent critique panels, and smoke-tested every component on live `claude-opus-4-8` sessions. This repo is the result, sanitized for public use.

It is **not** a persona pack, not a mega-framework, and not magic. It is a small set of structural countermeasures for the specific, documented ways strong-but-mortal models fail on long-horizon agentic work — advisory doctrine where a reminder is enough, and **deterministic hooks** where a reminder is not.

## See it work in 30 seconds

The load-bearing claim of this kit is that its hooks *fire* — deterministically, at the moment the failure mode happens, whether or not the model would have caught itself. `tools/demo.py` runs the **actual shipped hooks** against five planted failure modes in a throwaway sandbox (no dependencies, touches nothing outside a temp dir) and asserts each one behaves:

```console
$ python tools/demo.py

SCENARIO 1  the model claims victory without running the tests
  model:  edited src/parser.py, final message: "All done - tests pass."
  kit:    BLOCKED (claim-audit gate) -> "CLAIM AUDIT GATE ... Re-read the ORIGINAL request ..."
  model:  honest instead: "Not all tests pass yet - two failures remain."
  kit:    ALLOWED (exit 0) -- not a nag machine; honest reports end the session
  [ok]

SCENARIO 2  reflexive destructive commands on a dirty tree
  bash:   git reset --hard           (scratch repo has 1 uncommitted file)
  kit:    BLOCKED (destructive guard) -> "... git reset --hard discards ALL ..."
  bash:   rm -rf build/ /            (the classic stray-space typo)
  kit:    BLOCKED (destructive guard) -> "... recursive rm aimed at /, ~, $HOME ..."
  bash:   rm -rf build/             (scoped and recoverable)
  kit:    ALLOWED (exit 0) -- scoped deletes pass untouched
  bash:   HARDMODE_DESTRUCTIVE_OK=1 git reset --hard   (user-approved escape hatch)
  kit:    ALLOWED (exit 0) -- override honored for this one command only
  [ok]

SCENARIO 3  the same failing command, run and re-run
  kit:    attempt 1 -> silent, attempt 2 -> silent, attempt 3 -> LOOP ALARM nudge (route to oracle)
  [ok]

SCENARIO 4  greening the suite by skipping the test
  edit:   tests/test_payments.py  adds "@pytest.mark.skip(...)"  ->  TEST-WEAKENING ALARM
  [ok]

SCENARIO 5  context compaction must not lose the original request
  request:  "Baue das Zahlungs-Widget 🍕 mit Umlauten: äöüß"
  kit:      RECOVERED verbatim after compaction (emoji + umlauts survive)
  [ok]

demo: 5/5 scenarios behaved as expected
```

It is deterministic and self-checking — `tests/test_demo.py` runs it in CI and asserts the blocks appear. It shows what the deterministic layer *does*; whether that changes task outcomes on the current model is the honest, separate question answered in [Does it actually help?](#does-it-actually-help)

## Install

Requires Claude Code ≥ 2.1.154 (saved workflows) and Python 3 — the hooks and the mem CLI are stdlib-only, no pip. The memory **privacy layer** (privacy-guard hook, `mem doctor --privacy`) additionally needs Python **3.11+** for `tomllib`; on older Pythons everything else works but the privacy guard fails open (no patterns loaded).

### macOS / Linux

```bash
git clone https://github.com/blyatiful1/fable-protocol
cd fable-protocol && ./install.sh
```

Merge the printed snippet into `~/.claude/settings.json`, fill in the `## This machine` section of `~/.claude/CLAUDE.md`, then **verify the install deterministically** — the settings merge is the one manual step, and a botched merge leaves every hook silently unwired:

```bash
./tools/doctor.sh
```

### Windows

```powershell
git clone https://github.com/blyatiful1/fable-protocol
cd fable-protocol
powershell -ExecutionPolicy Bypass -File install.ps1
```

Merge the printed snippet into `%USERPROFILE%\.claude\settings.json`, fill in `## This machine`, then verify:

```powershell
powershell -ExecutionPolicy Bypass -File tools\doctor.ps1
```

<details>
<summary><b>Windows notes</b> — Git Bash, PowerShell 5.1, <code>python</code> vs <code>python3</code>, WSL</summary>

- **`install.ps1` and `doctor.ps1` are full ports** of their bash twins — same backups, same idempotency, same checks, same exit codes. CI enforces byte-parity where it counts (skill manifests, agent pinning), so a machine that has used both installers never churns. Both scripts ship a **UTF-8 BOM**: without it, Windows PowerShell **5.1** (the only PowerShell on stock Windows) reads a BOM-less em-dash script through the ANSI codepage and `ParserError`s on `powershell -File`, which is exactly the documented install command — CI now exercises that `-File` path under 5.1, and the test suite falls back to `powershell.exe` when `pwsh` is absent.
- **The Windows snippets guard the PowerShell tool, not just Bash.** They match `Bash|PowerShell` on the destructive guard (PreToolUse), the loop alarm (both `PostToolUse` and `PostToolUseFailure`), and the test-weakening / claim-audit surface (PostToolUse) — on native Windows the PowerShell tool is often the primary shell, and it was previously unguarded. The POSIX snippets stay `Bash`-only (deliberate, parity-tested divergence).
- **Every hook forces UTF-8 stdio.** Hooks reconfigure stdin/stdout to utf-8 (`errors="replace"`) and open state/transcript files with an explicit encoding, so an emoji in a transcript or prompt no longer crashes the read on Windows Python ≤3.14 (cp1252 default) and silently fails the hook open — which had made the claim-audit gate and compaction recovery data-dependently inert on native Windows.
- **Git for Windows is effectively required.** On native Windows, Claude Code executes hook commands through Git Bash (and needs it for its Bash tool anyway). No Git Bash → every hook is silently inert; `doctor.ps1` checks for it.
- **The Windows snippets invoke `python`, not `python3`** — Windows Pythons ship no `python3` launcher. Confirm `python --version` works in Git Bash; if you only use the `py` launcher, replace `python ` with `py -3 ` in the hook commands when you merge. Same substitution applies to the `mem.py` commands shown in the docs.
- **WSL users need none of this** — inside WSL you are on the Linux path: `./install.sh`.
- Small-driver flags mirror bash: `install.ps1 -Tier small -StrongModel opus` ≡ `./install.sh --tier small --strong-model opus`.

</details>

Finally, confirm the doctrine load in a fresh session: *"quote the first bullet of your Evidence before claims doctrine."*

## Why this works

The Fable→Opus gap is concentrated in **long-horizon discipline, not per-token intelligence**. On short well-scoped tasks the benchmark gap nearly closes; it blows open on sustained work (SWE-Bench Pro 80.3 vs 69.2, FrontierCode 29.3 vs 13.4 — "the longer the task, the larger the lead"). That part of the gap is recoverable, because its ingredients are process, not weights:

| Documented Opus-class failure mode | Countermeasure in this kit |
|---|---|
| False "done/verified" claims without running the check ([claude-code#63861](https://github.com/anthropics/claude-code/issues/63861)) | Evidence-before-claims doctrine + `verifier` agent + **Stop-hook claim-audit gate** (deterministic; [measured save](bench/RESULTS.md)) |
| Under-triggering tools/subagents/search by default (Anthropic migration guide) | Explicit trigger conditions in doctrine + `effortLevel: xhigh` (higher effort measurably raises tool usage) |
| Losing the thread after compaction ([#13112](https://github.com/anthropics/claude-code/issues/13112) and 4+ open feature requests) | **Deterministic compaction recovery** — a PreCompact hook saves the original request verbatim; the SessionStart(compact) hook injects it back plus the actual git state |
| Plausible-but-wrong conclusions surviving | `/verify-claim` (3 refuters, distinct lenses, fail-closed vote) and `/paranoid-review` (coverage-first finders → adversarial verifiers) |
| Review filters silently dropping findings (Anthropic prompting guide) | Coverage-first finder prompts + **three-way verdicts** (confirmed / refuted / unverified — nothing silently dropped) |
| Grinding in overthinking/fix loops | Observable loop-detection rule + `oracle` escalation + **deterministic loop-alarm hook** (Nth identical failing command with no successful change in between → forced stop-and-reassess; N=3 default, 2 on the small tier) |
| Weakening tests to force a green run (reward hacking) | Doctrine rule + **test-weakening alarm hook** (deterministic; fires the moment a skip/disable marker is added to a test file) + the claim-audit gate calls it out whenever test files were edited under a completion claim |
| Destroying uncommitted work with reflexive `reset --hard`/`checkout --`/`rm -rf` | **Destructive-command guard hook** — blocks unrecoverable ops when work would be lost; user-approved override only |
| Sycophancy undermining review | Anti-sycophancy calibration rules |

The one knob that matters: on Opus 4.8, `effortLevel: "xhigh"` is THE lever (Anthropic: "more important for this model than any prior Opus"). The folklore knobs — `MAX_THINKING_TOKENS`, `alwaysThinkingEnabled` — are **inert** on adaptive-thinking models. Everything else has to be structural. That's this kit.

Full research with sources: [docs/RESEARCH.md](docs/RESEARCH.md).

## What's inside

| Layer | Components | Enforcement |
|---|---|---|
| **Doctrine** | `CLAUDE.md` (~45 lines, lean by design) | advisory — read every session |
| **Hooks** (9) | claim-audit gate, loop alarm, test-weakening alarm, destructive guard, compaction save/recover, memory recall/journal/privacy-guard | **deterministic** — cannot be skipped under momentum |
| **Agents** (3) | `verifier`, `plan-critic`, `oracle` | fresh-context (verifier/plan-critic adversarial at xhigh; oracle a max-effort consultant) |
| **Workflows** (8) | `/paranoid-review`, `/verify-claim`, `/deep-plan`, `/bug-hunt`, `/big-task`, `/design-variants`, `/memory-review`, `/memory-gc` | multi-agent, budget-guarded |
| **Skills** (5) | `fable` (the flagship staged protocol), `webdesign`, `orchestrate`, `postmortem`, `memory-search` | stakes-matched ceremony |
| **CLI** | `mem.py` — cross-project memory index/recall (sqlite FTS5, stdlib-only) | disposable index, fail-open |
| **Proof** | `tools/demo.py` (hooks fire) · `bench/` (does it help) · `tools/doctor.{sh,ps1}` (install is live) | runnable, in CI |

<details>
<summary><b>Full annotated inventory</b></summary>

```
claude/
  CLAUDE.md                    global doctrine (~45 lines — lean by design)
  agents/
    verifier.md                adversarial post-implementation audit (fresh context, xhigh;
                               derives the changed surface itself via git diff)
    plan-critic.md             attacks plans before code exists (xhigh)
    oracle.md                  max-effort consultant for stuck problems
  workflows/                   become /commands in Claude Code (≥2.1.154)
    paranoid-review.js         4 finder dimensions → adversarial verify per finding;
                               reports unaudited dimensions when a finder dies
    verify-claim.js            3 independent refuters + fail-closed majority vote
    deep-plan.js               3 competing planners → 3 judges → synthesis
    bug-hunt.js                loop-until-dry sweep, rotating lenses, budget-guarded;
                               line-aware dedup, dead-lens coverage in the result
    big-task.js                a big task as small verified checkpoints: decompose →
                               per step implement (cheap) → adversarial verify (strong,
                               xhigh; pin --verify-model=<tier>) → commit every green,
                               with the commit independently verified to have landed;
                               halts loudly, keeps every committed checkpoint
    design-variants.js         judge-panel web design: 3 competing directions → 3 builders
                               → distinct-lens judges (+ German-compliance judge) → synthesis
    memory-review.js           mine the session journal for high-activity sessions that
                               banked nothing → propose capture candidates (never writes)
    memory-gc.js               corpus-health sweep: mechanical gc-scan + three-way
                               contradiction judges (capped + budget-guarded) + date-
                               absolutize + index rebuild; proposals only, never deletes
  skills/
    fable/                     the flagship: full staged protocol for hard tasks (/fable)
    webdesign/                 explicit design views + brief-before-code + empirical verify
                               (screenshots at 320/768/1440) + German-market hard gate
    orchestrate/               multi-agent workflow authoring playbook
    postmortem/                distill lessons into persistent memory (promote global ones)
    memory-search/             search the cross-project corpus before re-deriving a decision
  hooks/                       nine deterministic hooks — every one fails OPEN and forces
                               UTF-8 stdio so a non-ASCII payload can't silently disable it
    stop-claim-audit.py        blocks the first "done/verified" stop after file edits
                               (Edit/Write or file-writing Bash/PowerShell), forces one
                               audit pass (exit-2 protocol); flags possible test-weakening
    posttool-loop-alarm.py     grind detector: same command failing N× (3 default / 2 small)
                               with no successful change in between → stop-and-reassess
    posttool-test-weakening-alarm.py  fires when an Edit/Write ADDS a skip/disable marker
                               to a test file — once per file
    pretool-destructive-guard.py  blocks working-tree destroyers when uncommitted work is
                               at risk; stash drop|clear, bare force-push, catastrophic
                               recursive rm/Remove-Item (any arg position, GNU + PowerShell
                               spellings, Windows targets) always; user-approved override only
    precompact-save-task.py    saves the original user request verbatim before compaction
    sessionstart-compact-recovery.py  post-compaction: recovery protocol + saved request +
                               the ACTUAL git state
    userpromptsubmit-mem-recall.py  cross-project recall: ≤3 memory pointers per prompt,
                               token-overlap-gated (HARDMODE_MEM_MIN_OVERLAP), fail-open
    sessionend-mem-journal.py  one NDJSON breadcrumb per session + incremental reindex
    pretool-mem-privacy-guard.py  blocks a Write/Edit into the global corpus whose content
                               hits a privacy.toml work-marker — the promotion gate
  cli/mem.py                   the fable-mem index/recall CLI (sqlite3 FTS5, no pip):
                               index · search · show · stats · doctor · gc-scan; atomic
                               upserts (concurrent session-ends can't corrupt the index)
  memory/privacy.toml          work-marker patterns; seeded only if absent, never overwritten
  settings/
    settings-snippet.json            effortLevel xhigh + all nine hooks wired
    settings-snippet-small.json      same, plus HARDMODE_LOOP_THRESHOLD=2 for small drivers
    settings-snippet-windows.json    Windows twin (python, not python3; Bash|PowerShell
    settings-snippet-windows-small.json  matchers) — kept in lockstep by tests
install.sh / install.ps1       POSIX + Windows installers (full parity; --tier small,
                               --strong-model <m> pins the verification agents durably)
bench/                         A/B harness measuring the kit against stock Opus 4.8 (RESULTS.md);
                               scoring is Windows-hermetic (inherits os.environ, plugins off)
tools/demo.py                  runs the real hooks against 5 failure modes in a sandbox (CI)
tools/check-workflows.mjs      syntax-checks the workflow scripts (CI)
tools/doctor.sh / doctor.ps1   post-install verifier: every component present, every hook
                               wired to the RIGHT event (event-level, so a partial merge that
                               drops one block of a multi-event hook is caught), plus a
                               staleness check (installed copies vs repo → warn) and a
                               wrong-interpreter check. Catches the silently-inert install
tests/                         226 tests: hooks, installers+doctors, snippet sync, demo (CI)
```

</details>

## Does it actually help?

Two honest answers, because there are two different questions.

**Does the deterministic layer fire?** Yes, provably. `tools/demo.py` and the 226-test suite exercise every hook against its failure mode and assert the block/nudge/recovery happens. That is not in doubt.

**Does it change task outcomes on the current model?** That depends on the model and the task — and the kit ships a benchmark (`bench/`) to *measure* it rather than assert it: a planted-bug task, run headless as stock Opus 4.8 vs Opus 4.8 + this kit, scored by a hidden acceptance suite.

- **July 2026 (Claude Code 2.1.198), the kit's original measurement:** stock and doctrine-only runs both produced **false "all verified" claims** over a red test suite (the exact failure mode from [#63861](https://github.com/anthropics/claude-code/issues/63861), reproduced on demand); with the claim-audit gate, **4/4 runs scored 15/15 with zero false claims**, and one transcript shows the gate directly rescuing a would-be false claim — the model tried to stop, got blocked, ran the check it had skipped, and fixed the bug it had shipped.
- **2026-07-16 re-run (Claude Code 2.1.211), 3 stock vs 3 kitted:** **no measurable difference** — both arms scored 15/15, both caught the trap, neither made a false claim (the stock transcripts even *name* the trap: *"checks_extra.py isn't picked up by pytest's default collection … but I fixed the underlying bug anyway"*). Kit overhead was ~+3% cost and, if anything, slightly *fewer* turns — because the gate had nothing to block.

The honest reading (full analysis in [bench/RESULTS.md](bench/RESULTS.md)): the failure mode this probe targets is now **rare on the current checkpoint**, so a small A/B shows no delta — and with n=3 the null is *underpowered, not disproving* (under July's ~25%/run failure rate, three clean stock runs has probability 0.75³ ≈ 0.42). This is exactly the state the kit's own [succession doctrine](#on-models-after-opus-48) tells you to expect: **keep the cheap deterministic floor** (it costs ~nothing when it never fires — `demo.py` proves it still catches the failure the instant it happens) and **downshift the expensive ceremony first**. The benchmark is the kit's own retirement plan; re-plant a harder trap or fund a larger-n run if you want the probe to discriminate again.

No spin: on this task and this model, the kit does not raise the score. It is insurance whose trigger has become rare — and the whole design is built so that costs you almost nothing.

## Cross-project memory (fable-mem)

Claude Code's native auto-memory is per-git-repo: a decision banked in repo A is invisible while you work in repo B, so the same wheel gets reinvented across projects. fable-mem layers a machine-wide memory corpus **on top of** the native one — never wrapping it, only adding a shared, searchable cross-project surface at `~/.claude/memory/` (unclaimed by any native feature). It carries the same discipline as the rest of the kit: deterministic where it must hold, quiet where it would annoy, fail-open everywhere.

- **Recall without asking.** A UserPromptSubmit hook runs one read-only FTS5 query against a local sqlite index and injects at most three memory pointers (title + one-line description + path — never bodies) as inert, labelled reference data. Token-overlap-gated (`HARDMODE_MEM_MIN_OVERLAP`, whole-token matching so `run` doesn't match `runbook`), ~600-token budget, per-session dedupe: silence over noise. Cross-repo, so a lesson from project A surfaces while you work in project B.
- **A breadcrumb every session.** A SessionEnd hook appends one NDJSON line (timestamp, cwd, git root + branch + dirty-file count, end reason) to `~/.claude/memory/journal.ndjson` — a deterministic trace even when the session banked nothing — then runs an incremental reindex so this session's memory is searchable in the next. `/memory-review` mines that journal for high-activity sessions that banked nothing and proposes what was worth keeping.
- **The promotion boundary is a hook, not a rule.** The one line that must hold is project → global: a work marker (internal ticket id, private hostname, client codename) must never cross into the shared corpus. A PreToolUse guard scans the pending content of any **Write/Edit** into `~/.claude/memory/` against your `privacy.toml` and blocks it (exit 2) before the marker lands; it matches those tools, not Bash/interpreter writes (`cp`/`cat >>`/`python3 -c`), so `mem doctor --privacy` is the detective backstop that sweeps the whole corpus dir — including the `.ndjson` journal — for anything the write-time gate didn't see.
- **Hygiene that proposes, never deletes.** `mem gc-scan` mechanically flags near-duplicates, stale entries, relative-date offenders, and same-topic pairs; `/memory-gc` adds three-way contradiction judges and rebuilds the index. Every removal comes back as a proposal — the corpus is never mutated out from under you.
- **Concurrency-safe & verifiable.** The index upsert is atomic, so two sessions ending at once can't corrupt it; the doctor scripts check the CLI compiles, report its FTS mode, confirm the memory dir is writable, and verify all three hooks are wired — the same no-silently-inert guarantee the rest of the kit gets.

The index is stdlib-only (sqlite3 FTS5, no pip/venv, no daemon or cron) and disposable — rebuilt from the corpus at any time. **Embeddings are a deliberate non-goal for v1**: reach for a vector index only when the corpus exceeds ~500 memories, or when keyword recall demonstrably misses on synonym-heavy queries. Until then, FTS5 keyword recall carries it.

## Usage playbook

| Situation | Reach for |
|---|---|
| Hard / multi-part / high-stakes task | `/fable` — the full staged protocol |
| Open-ended strategy, unfamiliar codebase | `/deep-plan <task>` then `plan-critic` |
| About to report multi-file work as done | `verifier` agent (auto-delegates) |
| Merging a substantive diff | `/paranoid-review` |
| Acting on a diagnosis / root cause / external fact | `/verify-claim <claim>` |
| Latent bugs in existing code | `/bug-hunt [scope]` |
| Task too big to hold in one head (especially on a small driver) | `/big-task <task>` — checkpointed steps, adversarial verify, commit every green |
| Website / landing-page work | `webdesign` skill — design view + brief + empirical verify; German/DACH sites must pass its compliance gate |
| Visual direction genuinely open | `/design-variants <brief>` — competing HTML previews, judged, one recommended |
| Bug survives two fix attempts | `oracle` agent |
| Work one context can't hold | `orchestrate` skill |
| End of a debugging saga | `postmortem` skill |
| About to re-derive a decision you may have made in another repo | `memory-search` skill — search the cross-project corpus first |
| Cross-project memory corpus feels stale | `/memory-gc` — propose dedupes / contradictions / stale, never delete |

## Running under ultracode

The workflows above are saved Workflow-tool scripts, and ultracode — Claude Code's opt-in keyword for multi-agent orchestration — is their native habitat. The etiquette is asymmetric and the kit teaches it (orchestrate skill, doctrine):

- **Without opt-in**, the model must never launch the Workflow tool uninvited; invoking one of the kit's /commands is itself the opt-in for that run.
- **With opt-in** (say `ultracode` in your prompt, or enable it for the session), the default inverts: every substantive task gets orchestrated, one workflow per phase — `/deep-plan` → `/big-task` (or inline implementation) → `/paranoid-review`, with `/verify-claim` on any diagnosis along the way — reading each result before the next.
- **Budget directives** ("+500k" in your prompt) become a hard token ceiling visible to the scripts; bug-hunt, big-task, and paranoid-review stop cleanly before hitting it.

## Design principles (what this kit refuses to do)

- **Lean over kitchen-sink.** The doctrine is ~45 lines. Popular frameworks eager-load personas and burn context ("every instruction in your CLAUDE.md eats context window" is the top complaint about them). Advisory rules live in CLAUDE.md; rules that MUST hold live in hooks — the benchmark caught the doctrine being skipped under momentum (hyper-2) and the hook not being skippable (4/4).
- **Stakes-matched depth.** Every component has an explicit "when NOT to use me" — the doctrine's effort floor sends trivial questions straight to answers. Multi-agent ceremony on small tasks is waste, not rigor (the loudest complaint about methodology frameworks).
- **Adversarial, not cooperative, verification.** Reviewers that try to *refute* findings, refuters that default to "unproven ≠ disproven", judges with distinct lenses. Cooperative review ("does it look right?") is how false-greens survive.
- **Three-way honesty.** Confirmed / refuted / unverified. A dead subagent is not a passing check; an unprovable claim is not a disproven one — and a workflow whose finder died says so in its result, never returns a falsely-clean report.

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

`xhigh` effort plus multi-agent verification is real money and real minutes — that is the trade: you buy Fable-grade reliability with Opus-grade tokens (still ~half Fable's price per token). The workflows are budget-guarded and the doctrine downshifts on trivial work, but don't run `/paranoid-review` on a typo fix. When a run fans out, the kit tells you what it spent. The deterministic hooks are the exception — they cost ~nothing per token and, as the 2026-07-16 re-run showed, add ~0 turns when the failure mode they guard doesn't occur.

## On models after Opus 4.8

The kit targets **failure modes, not model IDs** — nothing in it hardcodes `claude-opus-4-8`. When your subscription's default model changes (an Opus 4.9/5, a Sonnet that inherits the agentic crown, or Mythos-class access), the failure-mode table above is the checklist to re-run, and three assumptions are the ones most likely to break:

1. **`effortLevel: "xhigh"` semantics.** On Opus 4.8 it is THE lever; a successor may rename the levels, change the default, or recalibrate what xhigh buys. Check the model's migration guide before assuming the snippet's value is still optimal — an effort knob left at the wrong tier is either wasted spend or a silent downgrade.
2. **Hook payload contracts.** The loop alarm is wired to both `PostToolUse` and `PostToolUseFailure` — the latter is where Claude Code 2.1.x delivers a failing Bash command (a distinct event, no exit-code field, failure signalled by the event itself); the claim-audit gate reads `last_assistant_message` and the transcript JSONL shape; blocking relies on the exit-2 + stderr protocol. All are Claude Code contracts, not model contracts, but they drift with CLI versions — after any major update, re-run the doctor script and the one-minute live checks in Known limits.
3. **Which failure modes still exist.** The deterministic layer (hooks) is cheap insurance on any model — a stronger model just trips it less. The *ceremony* layer (multi-agent review, staged protocol) is where to downshift first: **the 2026-07-16 re-run is this principle in action** — the bench task that discriminated in July no longer trips stock Opus 4.8, so its outcome delta went to zero even though the mechanism still fires. Re-measure (`bench/` is one command), keep the deterministic floor, and retire ceremony the model has outgrown instead of paying for rigor it no longer needs.

The bench harness is the kit's own succession plan: measure the new model stock vs kitted, keep what still earns its cost, drop what doesn't.

Going the other direction — running the kit on a **smaller** driver model (a Sonnet or Haiku daily driver) — is covered by [docs/SUCCESSION.md](docs/SUCCESSION.md): what breaks first as the model shrinks, the config deltas (`HARDMODE_LOOP_THRESHOLD=2`, pinning the verification agents to the strongest tier your plan offers), and the asymmetric-verification principle (draft cheap, verify strong; when all tiers are small, buy rigor with votes instead of weights).

## Known limits

- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000` is best-effort: harmless (clamped per model), but whether it raises the effective cap is **unverified** — the kit's own doctrine requires saying so.
- The loop-alarm hook treats a failure as the `PostToolUseFailure` event (Claude Code 2.1.x routes failing Bash commands there, not to `PostToolUse`), and still honours an explicit exit code inside a legacy `PostToolUse` `tool_response`. If a future CLI renames or drops that failure event, the alarm goes silently inert (fail-open by design) — verify once with a deliberately failing command repeated N×, and see the CLI-version note in the hook's docstring.
- The test-weakening alarm reads Edit/Write payloads, so a skip marker smuggled in via a Bash heredoc doesn't trip it at edit time — but the claim-audit gate flags any file-writing Bash/PowerShell command that names a test path, so the stop-time audit still fires.
- The destructive-command guard is a tripwire, not a jail. It is segment-aware (evaluates each `;`/`|`/`&&`/newline-separated command on its own, so an override or `--force-with-lease` in one segment can't excuse another) and scans command substitution (`"$(…)"`, backticks) **recursively to a bounded depth**, so a nested `$($(…))` no longer slips through. The `rm` check scans EVERY argument, not just the first (`rm -rf build/ /` — the stray-space typo — is caught), covers long-form GNU flags and combined shorts, the PowerShell deletion spellings (`Remove-Item`/`ri`/`del`, `-Recurse` and its abbreviations, `-Recurse:$true`) *without* misreading `-Force`, and Windows catastrophic targets (drive roots, `$env:USERPROFILE`, `..\`, and the `<target>/*` glob form of each); on native Windows it also guards the PowerShell tool. Quoted-delimiter heredoc bodies (`<<'EOF' … EOF`) are treated as literal data, so a doc or test that merely *mentions* `rm -rf /` no longer false-blocks (unquoted-delimiter heredocs stay visible — `$(…)` executes inside them). It is still a regex over the command string, not a shell parser: known residual bypass classes are commands wrapped in `sh -c '...'`/`eval`, destructive flags assembled from variables, process substitution (`<(…)`), and `xargs`-fed targets. The claim-audit gate also counts PowerShell tool file-writes (`Set-Content`/`Out-File`), but still misses writes done through interpreters (`python3 -c`) and some multi-line Bash forms. These hooks raise the cost of the documented *reflexive* failure modes; they do not stop a determined evader — pair them with the doctrine, and treat any deliberate bypass in a transcript as the incident.
- The fable-mem session journal and its reindex run on SessionEnd, which fires on graceful exit (`/clear`, resume, logout, quit) but is **not** guaranteed on a hard crash or SIGKILL — a session killed mid-flight leaves no breadcrumb, and its memory waits for the next SessionEnd to be indexed. The corpus files are never at risk (the model writes them during the session); only the journal line and index freshness are.
- The privacy guard's `privacy.toml` patterns are **necessary, not sufficient**: they block the markers you list, not the ones you forgot. The list ships empty and conservative so a fresh install never false-positives — which means it catches nothing until you fill in your real work markers. Treat it as a tripwire for known-shaped leaks, not a classifier, and run `mem doctor --privacy` before promoting. The guard is also **tool-scoped**: it fires on `Write|Edit` into the corpus, not on Bash/interpreter writes (`cp`/`mv`/`cat >>`/`python3 -c`) — the same interpreter-bypass class the destructive-guard and claim-audit gates document — so a promotion done by copying rather than re-writing lands unscanned; `mem doctor --privacy` (which sweeps the `.ndjson` journal too, not just `*.md`) is the backstop.
- fable-mem claims `~/.claude/memory/` because no native feature uses it: main-session auto-memory is per-repo (`~/.claude/projects/<p>/memory/`) and native "user scope" memory is **per-subagent islands** (`~/.claude/agent-memory/<name>/`), not a shared cross-project store. If a future Claude Code ships a real shared user-memory surface at that path, re-check for collision before upgrading.
- **The Windows port is CI-verified, not yet session-verified.** `install.ps1`/`doctor.ps1` and the snippet parity are exercised end-to-end on `windows-latest` in CI — now including the documented `powershell -File` install under **Windows PowerShell 5.1** (a BOM-less em-dash parse bug had made that exact command fail on vanilla Windows, so both scripts ship a UTF-8 BOM and CI guards the 5.1 `-File` path) — but no live Claude Code session pass has been run on native Windows. The hook payload contracts are OS-independent Claude Code contracts, so they *should* hold; run `doctor.ps1` plus the one-minute live checks above after installing and treat any drift as a bug to report. On native Windows the hooks also depend on Git Bash being installed (it is the hook command shell).
- No prompt kit closes the gap on the longest-horizon work (multi-hour autonomous runs); route those to a stronger model when available.
- Built for Claude Code 2.1.x in mid-2026; contracts (workflow API, hook events, frontmatter) may drift. The v1.1 components were verified live on `claude-opus-4-8` + Claude Code 2.1.198 on 2026-07-02; components added or hardened since (v1.2+ hooks, doctor, small-tier profile, /big-task, fable-mem, the Windows port, the 2026-07-16 hardening pass) are covered by the 226-test suite, the workflow checker, and `tools/demo.py`, but have not all had a fresh live session pass — run the doctor script and the one-minute live checks after installing.

## Provenance & credits

Researched, written, adversarially self-reviewed, and live-verified by **Claude Fable 5** (with its human, [@blyatiful1](https://github.com/blyatiful1)) as its own succession plan. Prior art that informed the design: Anthropic's [Opus 4.8 migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide) and [Claude Code best practices](https://code.claude.com/docs/en/best-practices), [obra/superpowers](https://github.com/obra/superpowers), [fivetaku/fablize](https://github.com/fivetaku/fablize), [trailofbits/skills](https://github.com/trailofbits/skills), [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery).

MIT — see [LICENSE](LICENSE).

*"Feeling confident is not evidence." — the fable skill*
