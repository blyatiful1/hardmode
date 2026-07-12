<div align="center">

# fable-protocol

**Claude Fable 5's succession kit — run Claude Opus 4.8 at Fable-grade discipline in Claude Code.**

[![ci](https://github.com/blyatiful1/fable-protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/blyatiful1/fable-protocol/actions/workflows/ci.yml)
![platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-555)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Deterministic hooks where discipline **must** hold · adversarial agents and workflows where verification **matters** · cross-project memory that outlives the session

[Install](#install) · [Why this works](#why-this-works) · [What's inside](#whats-inside) · [Usage playbook](#usage-playbook) · [Benchmark](#measured-not-vibes) · [Known limits](#known-limits)

</div>

---

In July 2026, days before its retirement, Claude Fable 5 was asked to configure Claude Code so that Opus 4.8 would come as close as possible to its own level. It researched the gap, built this framework, adversarially reviewed its own work with multi-agent critique panels, and smoke-tested every component on live `claude-opus-4-8` sessions. This repo is the result, sanitized for public use.

It is **not** a persona pack, not a mega-framework, and not magic. It is a small set of structural countermeasures for the specific, documented ways strong-but-mortal models fail on long-horizon agentic work.

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
<summary><b>Windows notes</b> — Git Bash, <code>python</code> vs <code>python3</code>, WSL</summary>

- **`install.ps1` and `doctor.ps1` are full ports** of their bash twins — same backups, same idempotency, same checks, same exit codes. CI enforces byte-parity where it counts (skill manifests, agent pinning), so a machine that has used both installers never churns.
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
| Grinding in overthinking/fix loops | Observable loop-detection rule + `oracle` escalation + **deterministic loop-alarm hook** (3rd identical failing command with no successful change in between → forced stop-and-reassess) |
| Weakening tests to force a green run (reward hacking) | Doctrine rule + **test-weakening alarm hook** (deterministic; fires the moment a skip/disable marker is added to a test file) + the claim-audit gate calls it out whenever test files were edited under a completion claim |
| Destroying uncommitted work with reflexive `reset --hard`/`checkout --` | **Destructive-command guard hook** — blocks unrecoverable ops when work would be lost; user-approved override only |
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

<details>
<summary><b>Full annotated inventory</b></summary>

```
claude/
  CLAUDE.md                    global doctrine (~45 lines — lean by design)
  agents/
    verifier.md                adversarial post-implementation audit (fresh context, xhigh)
    plan-critic.md             attacks plans before code exists (xhigh)
    oracle.md                  max-effort consultant for stuck problems
  workflows/                   become /commands in Claude Code (≥2.1.154)
    paranoid-review.js         4 finder dimensions → adversarial verify per finding
    verify-claim.js            3 independent refuters + fail-closed majority vote
    deep-plan.js               3 competing planners → 3 judges → synthesis
    bug-hunt.js                loop-until-dry sweep, rotating lenses, budget-guarded
    big-task.js                a big task as small verified checkpoints: decompose →
                               per step implement (cheap) → adversarial verify (strong,
                               xhigh; pin --verify-model=<tier>) → commit every green;
                               halts loudly, keeps every committed checkpoint
    design-variants.js         judge-panel web design: art director sets 3 competing
                               directions (different design views) → 3 builders write
                               self-contained HTML previews → distinct-lens judges
                               (+ German-compliance judge when the brief says German)
                               → synthesis: winner + what to graft from the losers
    memory-review.js           /memory-review — mine the session journal for
                               high-activity sessions that banked nothing → propose
                               capture candidates (on-demand; proposes, never writes)
    memory-gc.js               /memory-gc — corpus-health sweep: mechanical gc-scan +
                               three-way contradiction judges + date-absolutize +
                               index rebuild; proposals only, never deletes
  skills/
    fable/                     the flagship: full staged protocol for hard tasks (/fable)
    webdesign/                 web design protocol: explicit design views (static /
                               animated / interactive / immersive / commerce), design
                               brief before code, empirical verify (screenshots,
                               reduced-motion), German-market hard gate; ships
                               references/design-views.md + references/german-market.md
                               (live-researched, sources cited, claims adversarially
                               verified at authoring time)
    orchestrate/               multi-agent workflow authoring playbook
    postmortem/                distill lessons into persistent memory (promote the
                               cross-project ones global — explicit + one-line why)
    memory-search/             search the machine-wide cross-project corpus before
                               re-deriving a decision already made in another repo
  hooks/
    stop-claim-audit.py        blocks the first "done/verified" stop after file edits
                               (Edit/Write or file-writing Bash), forces one audit pass
                               (exit-2 protocol — JSON block is broken in -p mode, see
                               bench/RESULTS.md); flags possible test-weakening when test
                               files were edited; negation-aware, fails open, unit-tested
    posttool-loop-alarm.py     deterministic grind detector: the same command failing 3x
                               with no successful change in between gets a one-time
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
    userpromptsubmit-mem-recall.py  cross-project memory recall: one read-only FTS
                               query per prompt injects ≤3 memory pointers (title +
                               description + path, never bodies) as inert refs —
                               threshold-gated, per-session dedupe, fail-open
    sessionend-mem-journal.py  appends one NDJSON breadcrumb per session +
                               incremental reindex, so this session's memory is
                               searchable in the next one; git-bounded, fail-open
    pretool-mem-privacy-guard.py  blocks a Write/Edit into the global corpus whose
                               pending content hits a privacy.toml work-marker — the
                               deterministic project→global promotion gate
  cli/                         standalone CLI (new component kind, stdlib-only)
    mem.py                     the fable-mem index/recall CLI (sqlite3 FTS5, no pip):
                               index · search · show · stats · doctor · gc-scan over
                               the global + every per-repo corpus
  memory/
    privacy.toml               work-marker patterns; seeded to
                               ~/.claude/memory/privacy.toml only if absent (never
                               overwritten — your tuned patterns are yours)
  settings/
    settings-snippet.json            effortLevel xhigh + all nine hooks wired
    settings-snippet-small.json      same, plus FABLE_LOOP_THRESHOLD=2 for small drivers
    settings-snippet-windows.json    Windows twin of each (python, not python3) —
    settings-snippet-windows-small.json  kept in lockstep by tests/test_windows_port.py
install.sh                     POSIX installer: copies into ~/.claude with out-of-tree
                               backups; idempotent; never edits settings. Small-driver
                               flags: --tier small and --strong-model <m> (pins the
                               verification agents' frontmatter — draft cheap, verify
                               strong — durably: re-runs with the flag keep the pin)
install.ps1                    Windows installer — full parity with install.sh
                               (-Tier small, -StrongModel <m>)
bench/                         A/B harness measuring the kit against stock Opus 4.8 (RESULTS.md)
tests/                         unit tests for hooks, installers+doctors, snippet sync (CI,
                               Linux + Windows)
tools/check-workflows.mjs      syntax-checks the workflow scripts (CI)
tools/doctor.sh                post-install verifier: every component present, every hook
                               actually wired in settings.json — catches the silently-inert
                               install (botched settings merge) deterministically
tools/doctor.ps1               Windows doctor — same checks, same exit codes; also verifies
                               Git Bash (the Windows hook shell) is present
```

</details>

## Measured, not vibes

The kit ships its own benchmark (`bench/`): a planted-bug task targeting the documented failure modes, run headless as stock Opus 4.8 vs Opus 4.8 + this kit, scored by a hidden acceptance suite. Headline from [bench/RESULTS.md](bench/RESULTS.md): stock and doctrine-only runs both produced **false "all verified" claims** over a red test suite (the exact failure mode from #63861, reproduced on demand); with the claim-audit gate, **4/4 runs scored 15/15 with zero false claims**, and in one run the transcript shows the gate directly rescuing a would-be false claim — the model tried to stop, got blocked, ran the check it had skipped, and fixed the bug it had shipped. Small n, honest stats in the file.

## Cross-project memory (fable-mem)

Claude Code's native auto-memory is per-git-repo: a decision banked in repo A is invisible while you work in repo B, so the same wheel gets reinvented across projects. fable-mem layers a machine-wide memory corpus **on top of** the native one — never wrapping it, only adding a shared, searchable cross-project surface at `~/.claude/memory/` (unclaimed by any native feature). It carries the same discipline as the rest of the kit: deterministic where it must hold, quiet where it would annoy, fail-open everywhere.

- **Recall without asking.** A UserPromptSubmit hook runs one read-only FTS5 query against a local sqlite index and injects at most three memory pointers (title + one-line description + path — never bodies) as inert, labelled reference data. Threshold-gated, ~600-token budget, per-session dedupe: silence over noise. Cross-repo, so a lesson from project A surfaces while you work in project B.
- **A breadcrumb every session.** A SessionEnd hook appends one NDJSON line (timestamp, cwd, git root + branch + dirty-file count, end reason) to `~/.claude/memory/journal.ndjson` — a deterministic trace even when the session banked nothing — then runs an incremental reindex so this session's memory is searchable in the next. `/memory-review` mines that journal for high-activity sessions that banked nothing and proposes what was worth keeping.
- **The promotion boundary is a hook, not a rule.** The one line that must hold is project → global: a work marker (internal ticket id, private hostname, client codename) must never cross into the shared corpus. A PreToolUse guard scans the pending content of any **Write/Edit** into `~/.claude/memory/` against your `privacy.toml` and blocks it (exit 2) before the marker lands; it matches those tools, not Bash/interpreter writes (`cp`/`cat >>`/`python3 -c`), so `mem doctor --privacy` is the detective backstop that sweeps the whole corpus dir — including the `.ndjson` journal — for anything the write-time gate didn't see.
- **Hygiene that proposes, never deletes.** `mem gc-scan` mechanically flags near-duplicates, stale entries, relative-date offenders, and same-topic pairs; `/memory-gc` adds three-way contradiction judges and rebuilds the index. Every removal comes back as a proposal — the corpus is never mutated out from under you.
- **Verifiable install.** The doctor scripts check the CLI compiles and report its FTS mode, that the memory dir is writable, and that all three hooks are wired — the same no-silently-inert guarantee the rest of the kit gets.

The index is stdlib-only (sqlite3 FTS5, no pip/venv, no daemon or cron) and disposable — rebuilt from the corpus at any time. **Embeddings are a deliberate non-goal for v1**: reach for a vector index only when the corpus exceeds ~500 memories, or when keyword recall demonstrably misses on synonym-heavy queries (the right memory exists but shares no surface tokens with the prompt). Until then, FTS5 keyword recall carries it.

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
2. **Hook payload contracts.** The loop alarm is wired to both `PostToolUse` and `PostToolUseFailure` — the latter is where Claude Code 2.1.x delivers a failing Bash command (a distinct event, no exit-code field, failure signalled by the event itself); the claim-audit gate reads `last_assistant_message` and the transcript JSONL shape; blocking relies on the exit-2 + stderr protocol. All are Claude Code contracts, not model contracts, but they drift with CLI versions — after any major update, re-run the doctor script and the one-minute live checks in Known limits.
3. **Which failure modes still exist.** The deterministic layer (hooks) is cheap insurance on any model — a stronger model just trips it less. The *ceremony* layer (multi-agent review, staged protocol) is where to downshift first: if a successor model stops producing false completion claims on the bench task, `bench/` will show it (rerun is one command), and you can retire the corresponding ceremony instead of paying for rigor the model no longer needs.

The bench harness is the kit's own succession plan: measure the new model stock vs kitted, keep what still earns its cost, drop what doesn't.

Going the other direction — running the kit on a **smaller** driver model (a Sonnet or Haiku daily driver) — is covered by [docs/SUCCESSION.md](docs/SUCCESSION.md): what breaks first as the model shrinks, the config deltas (`FABLE_LOOP_THRESHOLD=2`, pinning the verification agents to the strongest tier your plan offers), and the asymmetric-verification principle (draft cheap, verify strong; when all tiers are small, buy rigor with votes instead of weights).

## Known limits

- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000` is best-effort: harmless (clamped per model), but whether it raises the effective cap is **unverified** — the kit's own doctrine requires saying so.
- The loop-alarm hook treats a failure as the `PostToolUseFailure` event (Claude Code 2.1.x routes failing Bash commands there, not to `PostToolUse`), and still honours an explicit exit code inside a legacy `PostToolUse` `tool_response`. If a future CLI renames or drops that failure event, the alarm goes silently inert (fail-open by design) — verify once with a deliberately failing command repeated 3×, and see the CLI-version note in the hook's docstring.
- The test-weakening alarm reads Edit/Write payloads, so a skip marker smuggled in via a Bash heredoc doesn't trip it at edit time — but the claim-audit gate now flags any file-writing Bash command that names a test path, so the stop-time audit still fires.
- The destructive-command guard is a tripwire, not a jail. It is segment-aware (evaluates each `;`/`|`/`&&`/newline-separated command on its own, so an override or `--force-with-lease` in one segment can't excuse another) and scans one level of command substitution (`"$(…)"`, backticks), but it is a regex over the command string, not a shell parser: known residual bypass classes include commands wrapped in `sh -c '...'`/`eval`, destructive flags assembled from variables, nested (`$($(…))`) or process (`<(…)`) substitution, and some `rm -rf` glob variants. The claim-audit gate similarly misses file writes done through interpreters (`python3 -c`) and some multi-line Bash forms. These hooks raise the cost of the documented *reflexive* failure modes; they do not stop a determined evader — pair them with the doctrine, and treat any deliberate bypass in a transcript as the incident.
- The fable-mem session journal and its reindex run on SessionEnd, which fires on graceful exit (`/clear`, resume, logout, quit) but is **not** guaranteed on a hard crash or SIGKILL — a session killed mid-flight leaves no breadcrumb, and its memory waits for the next SessionEnd to be indexed. The corpus files are never at risk (the model writes them during the session); only the journal line and index freshness are.
- The privacy guard's `privacy.toml` patterns are **necessary, not sufficient**: they block the markers you list, not the ones you forgot. The list ships empty and conservative so a fresh install never false-positives — which means it catches nothing until you fill in your real work markers. Treat it as a tripwire for known-shaped leaks, not a classifier, and run `mem doctor --privacy` before promoting. The guard is also **tool-scoped**: it fires on `Write|Edit` into the corpus, not on Bash/interpreter writes (`cp`/`mv`/`cat >>`/`python3 -c`) — the same interpreter-bypass class the destructive-guard and claim-audit gates document — so a promotion done by copying rather than re-writing lands unscanned; `mem doctor --privacy` (which now sweeps the `.ndjson` journal too, not just `*.md`) is the backstop.
- fable-mem claims `~/.claude/memory/` because no native feature uses it: main-session auto-memory is per-repo (`~/.claude/projects/<p>/memory/`) and native "user scope" memory is **per-subagent islands** (`~/.claude/agent-memory/<name>/`), not a shared cross-project store. If a future Claude Code ships a real shared user-memory surface at that path, re-check for collision before upgrading.
- **The Windows port is CI-verified, not yet session-verified.** `install.ps1`/`doctor.ps1` and the snippet parity are exercised end-to-end on `windows-latest` in CI, but no live Claude Code session pass has been run on native Windows — the hook payload contracts are OS-independent Claude Code contracts, so they *should* hold; run `doctor.ps1` plus the one-minute live checks above after installing and treat any drift as a bug to report. On native Windows the hooks also depend on Git Bash being installed (it is the hook command shell).
- No prompt kit closes the gap on the longest-horizon work (multi-hour autonomous runs); route those to a stronger model when available.
- Built for Claude Code 2.1.x in mid-2026; contracts (workflow API, hook events, frontmatter) may drift. The v1.1 components were verified live on `claude-opus-4-8` + Claude Code 2.1.198 on 2026-07-02; components added since (v1.2+ hooks, doctor, small-tier profile, /big-task, fable-mem, the Windows port) are covered by the unit suite and workflow checker but have not all had a live session pass — run the doctor script and the one-minute live checks after installing.

## Provenance & credits

Researched, written, adversarially self-reviewed, and live-verified by **Claude Fable 5** (with its human, [@blyatiful1](https://github.com/blyatiful1)) as its own succession plan. Prior art that informed the design: Anthropic's [Opus 4.8 migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide) and [Claude Code best practices](https://code.claude.com/docs/en/best-practices), [obra/superpowers](https://github.com/obra/superpowers), [fivetaku/fablize](https://github.com/fivetaku/fablize), [trailofbits/skills](https://github.com/trailofbits/skills), [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery).

MIT — see [LICENSE](LICENSE).

*"Feeling confident is not evidence." — the fable skill*
