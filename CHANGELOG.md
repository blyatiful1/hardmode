# Changelog

## v3.0 — 2026-08-30 — the premise inversion, and the rename to *hardmode*

The founding premise died. fable-protocol was written 2026-07-02 as a succession package
so Claude **Opus 4.8** could work at Fable-5 discipline; the driver is now **Fable 5
itself**, and Claude Code 2.1.x grew native equivalents for roughly half the kit. A
13-agent audit (every component read, the hooks driven with synthetic payloads, the
installer and bench run in a sandbox, ~1.9M tokens) drove this redesign.

**Renamed** `fable` → `hardmode` (skill, env-var prefix `HARDMODE_*`, state dir, backup
dir, manifest). The old name was a self-reference — a skill telling Fable 5 to "act like
Fable 5" degenerates to "be yourself, with more steps".

**Re-premised.** The doctrine now leads with mechanism, not lineage: *a deterministic
floor plus independent verification*. The verification agents earn their cost by being
**independent** (fresh context, refute-by-default), not by running a stronger model —
the original *draft-cheap/verify-strong* asymmetry inverts when the driver is the
strongest model on the machine, so workflow agents are now pinned *down* to opus/sonnet,
never inheriting the driver. Added a "who owns what" routing table (native
`/code-review`, `/simplify`, the web suite, the recall layer, the `oracle` ladder).

**Repackaged as a native Claude Code plugin** (`.claude-plugin/plugin.json` +
`hooks/hooks.json` via `${CLAUDE_PLUGIN_ROOT}`). Deleted `install.sh`, `tools/doctor.sh`
and the four settings snippets — the manual `settings.json` merge they policed was the
root cause of the machine's drift (four hooks unwired for ~8 weeks). A plugin makes that
failure class structurally impossible and brings versioning, uninstall and eval for free.

**Deleted (~49% of the tree)**, each with its replacement named:
- **fable-mem** (mem CLI, journal/recall hooks, memory-gc/review workflows,
  memory-search skill, 67 tests) — zero-byte corpus, never installed, displaced by the
  operator's own recall layer. The privacy guard survives.
- **Windows port** (install.ps1, doctor.ps1, 2 snippets, its tests) and the **small
  tier** — never ran a live session; `--strong-model` was a no-op that lied.
- **bench A/B** (run.sh, PROMPT.txt) — pinned to a retired model and non-discriminating
  by its own data. The task fixture + claim-regex sync-guard stay as regression tests;
  native `claude plugin eval --ablation` replaces the A/B.
- **webdesign + design-variants** — superseded by the operator's web suite.
- **big-task** — built for a small forgetful driver that no longer exists.
- **test-weakening alarm** — measured 0 true positives in 34 real firings; the
  claim-audit addendum keeps the rule advisory.

**Hardened the surviving guard hooks** against bypasses the audit proved by probe:
the destructive guard now judges dirtiness in the directory a command actually operates
on (`cd`/`git -C`), scans through `bash -c`/`eval` wrappers, and blocks `rm -rf` of a
literal system or home dir; the loop alarm no longer lets a diagnostic `tee`/redirect
wipe its grind counter; the claim-audit gate now covers **German** completions (it was a
silent false-pass for half the operator's messages) and stops false-blocking "resolved
to/by" prose.

Suite: 249 collected → focused set, all green; `claude plugin validate --strict` passes;
`tools/demo.py` 4/4.

## v2.1 — 2026-07-16

Adversarial re-audit. A 52-agent finder/verifier fleet plus manual review turned the kit
on itself again, this time targeting the Windows port and the enforcement layer's
data-dependent silent-failure modes. Two findings set the tone: on native Windows the
flagship claim-audit gate and compaction recovery were provably inert whenever a transcript
held an emoji (cp1252 default → UnicodeError → the fail-open wrapper silently DISABLED the
hook), and the machine this audit ran on had been executing 3-days-stale hooks under a fully
green doctor report. Both are now closed with tests. Suite: 219 passed, 23 skipped on native
Windows (baseline before: 6 failures); ~34 new regression tests.

This entry also folds in four destructive-guard commits that landed after the v2.0 changelog
was written but were never logged (all 2026-07-12): per-segment override scoping + a
CLAUDE_DIR docs fix (`93144a1`), regressions caught by adversarial self-review of that diff
(`58a6f0f`), newline segments / command-substitution scanning / an `rm` false-positive
(`9e07520`), and coherent substitution scanning — single-quote handling, inner separators,
`${HOME}` (`d79c529`).

### Fixed — enforcement layer (Windows made the "deterministic" hooks data-dependently inert)
- **UTF-8 systemic fix.** Every hook now reconfigures stdio to utf-8/`replace` and opens
  transcripts and state files with an explicit encoding. Before, an emoji in a transcript or
  payload crashed the read on Windows Python ≤3.14 (cp1252 default) and the fail-open wrapper
  silently DISABLED the hook — so the claim-audit gate and compaction recovery were inert on
  native Windows exactly when a session got interesting.
- **PowerShell tool coverage.** The Windows snippets now match `Bash|PowerShell` on the
  destructive guard (PreToolUse) and the loop alarm (both `PostToolUse` and
  `PostToolUseFailure`); the claim-audit gate counts PowerShell `tool_use` file-writes
  (Set-Content/Out-File/…, with `> $null` correctly NOT a write) and the loop alarm tracks
  PowerShell command grind. On native Windows the PRIMARY shell tool was previously entirely
  unguarded. POSIX snippets are unchanged (deliberate divergence, parity-tested).
- **Destructive-guard `rm` check rebuilt.** ALL arguments are scanned, not just the first
  (`rm -rf build/ /` — the stray-space typo — now blocks), plus long-form flags
  (`--recursive`), the PowerShell spellings (Remove-Item/ri/del, `-Recurse` + prefix
  abbreviations), Windows targets (drive roots `C:\`, `$env:USERPROFILE`, backslash forms),
  and `--` end-of-options. Quoted-delimiter heredoc bodies (`<<'EOF'`) are blanked as literal
  data so docs/tests that MENTION `rm -rf /` no longer false-block; unquoted-delimiter
  heredocs stay visible (`$(…)` executes inside). The previously documented nested `$($(…))`
  residual was REFUTED by testing (bounded-depth recursion catches it) and removed from Known
  limits; still-true residuals: `sh -c`/`eval` wrapping, variable-assembled flags, process
  substitution `<(…)`, xargs-fed targets.
- **Claim-audit gate: suite-claim negations.** "Not all tests pass yet" / "no checks are
  green" no longer false-block (they contain the positive substring "all tests pass").
- **Loop-alarm nudge wording is now threshold-agnostic** ("Another identical attempt…"),
  matching `FABLE_LOOP_THRESHOLD=2` on the small tier; the doctrine line tracks it.

### Fixed — fable-mem
- **`mem.py` upsert is now atomic** (INSERT … ON CONFLICT DO UPDATE): two SessionEnd
  reindexes closing near-simultaneously no longer crash the loser with a UNIQUE-constraint
  IntegrityError.
- **Recall relevance gate is token-boundary, not substring** ("run" no longer matches inside
  "runbook") in both the recall hook and `mem.py`'s degraded search; the recall keyword-count
  knob is renamed **`FABLE_MEM_MIN_OVERLAP`**, decoupled from `mem.py`'s bm25-scale
  `FABLE_MEM_MIN_SCORE` — they were the same env var, so tuning recall silently reconfigured
  (and could blank out) CLI search on an incompatible scale.
- **UTF-8 hygiene** across all three mem hooks.

### Changed — workflows (three-way honesty)
- **paranoid-review** returns `unauditedDimensions` when a finder dies (an unreviewed lens
  must never read as clean). **bug-hunt** returns dead-lens / coverage info and its dedup key
  now includes the line number (two different bugs with similar titles in one file no longer
  collide). **big-task** requires the implementer to return a commit hash and then
  INDEPENDENTLY verifies the commit landed (clean tree + matching HEAD subject) before a step
  counts green. **memory-gc**'s judge fan-out is capped (30, logged) and budget-guarded, with
  over-cap / budget-skipped pairs surfaced UNVERIFIED rather than dropped.
- **check-workflows.mjs** strips string literals and comments before the
  `Date.now()`/`Math.random()`/`new Date()` determinism ban, so a prompt that merely names
  those anti-patterns no longer false-fails (real code inside `${…}` interpolations is still
  scanned).

### Fixed — installers, doctors, bench
- **`install.ps1` + `doctor.ps1` now carry a UTF-8 BOM.** Without it, Windows PowerShell 5.1
  (the ONLY PowerShell on stock Windows) `ParserError`'d on the BOM-less em-dash scripts via
  `powershell -File` — the exact documented install command — so the README's install was
  completely broken on vanilla Windows (CI had only tested pwsh). CI gains a `shell: powershell`
  5.1 `-File` step, and the test suite falls back to `powershell.exe` when `pwsh` is absent.
- **Both doctors now do event-level wiring checks** (a partial merge dropping the loop alarm's
  `PostToolUseFailure` block is caught; the widened `Bash|PowerShell` matcher is accepted),
  gained a **staleness check** (installed `~/.claude` copies compared CRLF-normalized and
  agent-model-pin-aware against the repo; drift → warn — motivated by the live 3-days-stale
  hooks under a green doctor report), and `doctor.sh` gained the wrong-interpreter check (a
  Windows `python` snippet merged on POSIX).
- **bench:** `score.py` inherits `os.environ` (incl. `SYSTEMROOT` — fixes WinError 10106)
  while still pinning PATH/HOME, and is now plugin-hermetic
  (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`); `run.sh` detects `.venv/bin` vs `.venv/Scripts`;
  `score.py`'s NEGATED regex stays synced with the Stop-hook gate (test-enforced); RESULTS.md's
  aggregate cost sentence now names its baselines.

### Changed — agents, skills, docs honesty
- **`verifier.md`** step 1 now derives the changed surface itself via `git status`/`git diff`
  instead of trusting the caller's file list — an omitted file is exactly where a false green
  hides.
- Small-tier snippet comments no longer call `effortLevel` "an Opus-family knob": Sonnet 5 is
  adaptive-thinking and honors it.
- Docs made truthful again against the code: README Known-limits (destructive guard, Windows
  port, UTF-8), the Windows-notes block (PowerShell matcher divergence, PS 5.1/BOM,
  `powershell.exe` fallback), and the changed "What's inside" annotations (guard, both doctors,
  bench, workflow return fields); SUCCESSION.md's `effortLevel` config-delta; the fable skill's
  Stage 0 (nonexistent `TaskCreate` → an explicit TodoWrite/numbered task list); the webdesign
  skill's W3 screenshot widths (360 → 320, matching its own reflow invariant).

## v2.0 — 2026-07-12

Self-audit pass. The kit was turned on itself: a multi-agent audit swept every subsystem
(hooks, workflows, skills, agents, installers, mem CLI, bench, tests, docs), and every
candidate defect was adversarially verified against the code before it counted. 91 findings
survived verification; this release fixes the load-bearing ones and removes dead weight.
The headline is a real instance of the exact failure the kit exists to kill — a
"deterministic" enforcement hook that was silently inert — found in the kit itself and
proven fixed with tests. Suite: 166 → 183 passing (+13 skipped, unchanged).

### Fixed — enforcement layer (the hooks that must hold)
- **The loop alarm was deterministically inert on Claude Code 2.1.x.** Verified against the
  2.1.207 bundle: a failing Bash command fires `PostToolUseFailure` (a distinct event, no
  exit-code field — failure is signalled by the event itself), NOT `PostToolUse`, where the
  hook was registered and where it keyed on `tool_response.exit_code` — a field 2.1.x never
  sends. The kit's headline "deterministic loop alarm" never fired. The hook is now wired to
  **both** events (`PostToolUseFailure` for failures, `PostToolUse` for the successes that
  reset the grind counter), treats the failure event as the signal, and still honours legacy
  exit codes. New unit tests replay real-shaped failure payloads and prove the Nth failure
  trips the nudge.
- **Loop alarm cleared its own count on a failing write-command** (`make test > build.log`):
  the write heuristic ran before failure detection, so a redirecting grind reset itself every
  run and never tripped. The reset now happens only on SUCCESS.
- **Test-weakening alarm & claim-audit gate were inert on Windows paths.** `TEST_PATH` matched
  forward slashes only, so the `tests/`-dir and `test_*.py` heuristics never fired on native
  Windows (backslash `file_path`). Separators are now normalized in both hooks; added
  backslash-path tests.
- **Destructive-guard bypasses closed:** `--force-with-lease` in any *other* segment no longer
  excuses a bare `--force`; `git checkout ./` and `git checkout ..` now block on a dirty tree;
  and `FABLE_DESTRUCTIVE_OK=1` must be an actual env-assignment prefix — merely mentioning it in
  a quoted commit message no longer disables the guard.
- **Compaction recovery could lose its whole injection** on a slow repo: two 8s git calls under
  a 10s hook timeout. The protocol text and saved original request are now flushed BEFORE any
  git call, and the git budget is bounded (3s/call).
- **Hook state dir now honours `CLAUDE_DIR`** (was hardcoded `~/.claude`), matching the installer
  and the doctor's own probe.

### Fixed — mem CLI
- `search`/`show` no longer traceback on a schema-less index (0-byte / clobbered db) — it fails
  soft like any corrupt index and self-heals on `index --rebuild`.
- `gc-scan` no longer emits an N-choose-2 explosion of bogus "identical name" duplicate proposals
  for native per-project `MEMORY.md` files (filename-fallback names are excluded).
- `REL_DATE` no longer flags bare "now"/"recently" in ordinary prose ("we now use tabs").
- fts5 and degraded search now tokenize identically, so a query can't hit in one mode and miss in
  the other.
- `doctor --privacy` now warns that `mem-index.db` embeds project-memory bodies verbatim and must
  not be shared — the pattern scan can't read binary sqlite.

### Fixed — workflows, installers, bench
- `big-task`: `--verify-model` no longer secretly upgrades the *planners* (draft cheap / verify
  strong); the halt reason distinguishes "repair implementer died" from "failed verification
  twice"; malformed `--max-steps` is rejected, not swallowed.
- `bug-hunt`, `memory-gc`, `memory-review`, `paranoid-review`, `design-variants`: honest exit-cause
  messages, correct dry-run counts, leftover-arg rejection, budget-path dedup, and a two-signal
  German-market heuristic (a single umlaut no longer flips English briefs into German mode).
- `check-workflows.mjs` now scopes the meta-field check to the meta literal and fails on
  `Date.now()`/`Math.random()`/`new Date()` (resume-breaking non-determinism).
- `install.sh`: locale-independent (`LC_ALL=C`) manifest sort to preserve byte-parity with the
  PowerShell installer; `--help` prints only the header block.
- `doctor.sh`: python3-dependent checks are skipped-with-warn when python3 is absent instead of
  cascading false "does not compile"/"not valid JSON" FAILs; both doctors gained the Claude Code
  ≥ 2.1.154 version check.
- `bench/run.sh` canonicalizes relative `<runs-root>`/`<config-dir>` before `cd`; `bench/score.py`
  guards missing chore files, survives a hung acceptance run, preserves the caller's `PATH`, and
  its claims audit is now negation-aware (in sync with the Stop-hook gate). Added behavioral
  score.py tests.

### Changed — doctrine & docs honesty
- The `fable` skill no longer self-authorizes Workflow runs on auto-trigger; doctrine no longer
  tells the model to self-launch `/memory-gc` (both now defer to the orchestration opt-in gate).
- Doctrine's destructive-guard description corrected (it does not guard history rewrites).
- README: privacy-seed path, agent table, Python 3.11 note for the privacy layer, and the
  loop-alarm known-limit all corrected to match the code; RESEARCH's "every component
  live-verified" claim scoped to v1.0/v1.1.

### Removed
- `claude/cli/privacy.toml.example` — a dead, byte-identical duplicate of `claude/memory/privacy.toml`
  that nothing installed or read.
- `MultiEdit` — the tool no longer exists in Claude Code 2.1.x; removed from every settings
  matcher, the alarm hooks' `MODIFYING_TOOLS` sets and edit branch, and the user-facing docs.
  (The privacy guard keeps a generic batch-`edits` scan as forward-compat defense, no longer
  named after MultiEdit.)
- Dead code: `big-task.js`'s unused `commits` array, `mem.py`'s unused `FTS_COLUMNS`, a redundant
  settings-JSON test, and a no-op `env=os.environ.copy()`.

## v1.9 — 2026-07-09

Windows pass + README redesign. The kit's discipline layer was always OS-portable — the
hooks and the mem CLI are stdlib Python with `expanduser`/`os.path` throughout, and the
privacy guard already probed for case-insensitive filesystems — but the delivery layer
(bash installer, bash doctor, `python3 ~/...` hook commands) was POSIX-only, so on native
Windows the kit was silently uninstallable. This release makes Windows a first-class
install target with the same no-silently-inert guarantees, and restructures the README
around the reader (install first, story second, inventory collapsible).

### Added
- **`install.ps1` — native Windows installer, full parity with `install.sh`.** Same
  out-of-tree backups, same hash-based idempotency, same `.fable-manifest` skill
  tracking with stale-file pruning, same `-Tier small` / `-StrongModel <m>` flags,
  same never-edit-settings posture. Parity is enforced, not asserted: tests pin the
  skill manifests byte-for-byte across both installers and require that running
  `install.ps1` over a bash-installed tree reports everything unchanged (a dual-boot /
  WSL+native machine must never churn backups). Python launcher discovery tries
  `py -3`, `python`, `python3` in order and soft-fails like the bash bootstrap.
- **`tools/doctor.ps1` — native Windows doctor, same checks and exit codes as
  `doctor.sh`**, plus two Windows-only diagnoses: Git Bash present (on native Windows
  it is the hook command shell — absent means every hook is inert, a FAIL), and a
  warning when `settings.json` wires hooks through `python3` (a Unix snippet merged on
  Windows never fires — the exact silently-inert failure the doctor exists to catch).
- **Windows settings snippets** (`settings-snippet-windows.json`,
  `-windows-small.json`): identical to the Unix snippets except hook commands invoke
  `python` (Windows Pythons ship no `python3` launcher). `tests/test_windows_port.py`
  keeps them in lockstep structurally — any drift from the tested Unix configuration
  fails CI.
- **`tests/test_windows_port.py`** — snippet-mirror guards (run everywhere) plus
  pwsh-gated end-to-end tests mirroring `test_install_doctor.py`: install twice
  (idempotent, no backup churn), user files in skill dirs preserved, formerly-shipped
  files pruned, strong-model pin byte-identical with bash, doctor pass/fail/unwired
  scenarios. The POSIX-installer tests now self-skip on Windows instead of driving
  bash scripts through Git Bash.
- **CI `windows` job** (`windows-latest`): compiles every Python component, runs
  `install.ps1` end-to-end twice, verifies the merged install with `doctor.ps1`, and
  runs the unit suite. The Ubuntu job additionally parse-checks both `.ps1` scripts
  and validates all four settings snippets.

### Changed
- **README redesigned.** Install (macOS/Linux and Windows side by side, with a
  collapsible Windows-notes block) now leads; the origin story is two paragraphs, not
  a wall; the full annotated file tree is collapsible behind a six-row component-layer
  table; badges + section nav on top. Every honest-limits paragraph survives, plus a
  new one: the Windows port is CI-verified end-to-end but has not yet had a live
  Claude Code session pass on native Windows.
- Shipped components that name the mem CLI (`claude/CLAUDE.md` doctrine line,
  `memory-search` skill, `/memory-gc` agent prompts) now note the Windows spelling:
  `python` wherever a command says `python3`.

## v1.8 — 2026-07-08

Memory pass: the kit stops forgetting across projects. Native auto-memory is per-git-repo,
so a decision banked in one repo is invisible in the next — fable-mem layers a machine-wide,
searchable memory corpus **on top of** the native one (never wrapping it) at the unclaimed
`~/.claude/memory/`, with the kit's usual posture: deterministic where it must hold, quiet
where it would annoy, fail-open everywhere. Embeddings stay a deliberate non-goal for v1
(stdlib sqlite3 FTS5 only; the vector index waits for ~500 memories or demonstrated
synonym-recall misses).

### Added
- **`cli/mem.py` — a new component kind.** A single stdlib-only Python file (sqlite3 FTS5,
  no pip/venv) exposing `index · search · show · stats · doctor · gc-scan` over the L1 global
  corpus (`~/.claude/memory/*.md`) AND every native per-repo corpus
  (`~/.claude/projects/*/memory/*.md`), each row scope-tagged. FTS5 is probed at DB-open and
  degrades to a plain-table `LIKE` scan when absent; `doctor` reports the active mode. The
  index is disposable (rebuildable from the corpus), commits per-file so a timeout-kill
  preserves progress, and never mutates a memory file. Because it isn't a hook/agent/
  workflow/skill, it gets hand-written `install.sh` copy + bootstrap and `tools/doctor.sh`
  check blocks (the four existing globs don't see it).
- **Cross-project recall hook (`userpromptsubmit-mem-recall.py`, UserPromptSubmit).** One
  read-only FTS query per prompt injects at most three memory pointers (title + one-line
  description + path — never bodies) as inert, labelled reference data. Threshold-gated,
  ~600-token budget, per-session dedupe under `FABLE_STATE_DIR`; opens the index `mode=ro`
  and never builds on the prompt path (stale → silent). Fail-open: a malformed payload, a
  missing/locked index, or any bug ends in `exit 0` with no output, so the prompt is never
  lost. Prompt-injection-inert formatting (control chars stripped, quoted refs, never file
  bodies).
- **Session-journal hook (`sessionend-mem-journal.py`, SessionEnd).** Appends exactly one
  NDJSON breadcrumb per session (ISO ts, cwd, git root + branch + dirty-file count, end
  reason — computed via `git` subprocesses bounded by BOTH a per-call `timeout=` AND a small
  total wall-clock budget, since SessionEnd carries no native metadata beyond `reason`) to
  `~/.claude/memory/journal.ndjson`, rotates at 5MB, then runs an incremental `mem index` so
  this session's memory is searchable next session. The line is written **before** the reindex,
  and both settings snippets declare an explicit `"timeout": 10` (the SessionEnd default is
  1.5s, which would kill the hook and lose the breadcrumb); the total git budget stays well
  under that 10s so a slow/hanging git can never delay the append past the kill. Fail-open.
- **Privacy-guard hook (`pretool-mem-privacy-guard.py`, PreToolUse on `Write|Edit|MultiEdit`).**
  The deterministic project→global promotion gate: a `Write|Edit|MultiEdit` whose target
  resolves under `~/.claude/memory/` has its pending content (`content`/`new_string`) scanned
  against the user's `privacy.toml` work-markers; a hit `exit 2`s and blocks the write
  **before** the marker lands. It matches those tools, not Bash/interpreter writes (`cat >>`,
  `python3 -c`) — `mem doctor --privacy` is the backstop for those. Writes outside the corpus
  and clean payloads pass untouched; unloadable patterns fail open (a guard that can't read
  patterns can't honestly block). Advisory SKILL.md text was never enough — under momentum the
  model promotes anyway.
- **`memory-search` skill** — search the machine-wide corpus before re-deriving a decision
  already made in another repo; when to search, when NOT (facts visible in the current
  repo/git/CLAUDE.md), and how to promote a project lesson to global.
- **`/memory-review` workflow** (`claude/workflows/memory-review.js`) — mines the session
  journal for high-activity sessions that banked ZERO cross-project memories, then a
  three-way judge PROPOSES the durable lessons worth capturing. On-demand only; proposes,
  never writes (banking still happens explicitly via postmortem).
- **`/memory-gc` workflow** (`claude/workflows/memory-gc.js`) — corpus-health sweep:
  mechanical `mem gc-scan` (near-dup / stale / relative-date / same-topic candidates) →
  LLM contradiction judges with three-way verdicts on same-topic pairs → absolutize relative
  dates in place → rebuild the disposable index → report. NEVER deletes — every removal comes
  back as a proposal. (The mechanical `gc-scan` layer is test-covered; the workflow's LLM
  verdict layer is compile-checked only, like every workflow, and labelled unproven-by-harness.)
- **`postmortem` skill → v2** — a promotion rule (project→global only when explicit, with a
  one-line why-global; advisory, since the deterministic gate is the privacy-guard hook), a
  `visibility: private|shareable` field, an `open-loop` memory type, and hygiene rules
  (falsifiable conclusions, update-don't-duplicate, delete-what-evidence-refutes).
- **`claude/memory/privacy.toml`** — the work-marker pattern seed, conservative and shipping
  EMPTY (necessary-not-sufficient by design); `install.sh` copies it to
  `~/.claude/memory/privacy.toml` only if absent and bootstraps `mem index --rebuild` once so
  the corpus is indexed before any SessionEnd fires.
- Doctrine pointer (`claude/CLAUDE.md`): search the cross-project corpus before re-deriving,
  promote worth-keeping lessons global via postmortem, run `/memory-gc` when the corpus feels
  stale. README gains a fable-mem section, tree entries, playbook rows, and three Known-limits
  entries (the SessionEnd crash gap, patterns-necessary-not-sufficient, per-subagent memory
  islands).
- `tests/test_mem_cli.py`, `tests/test_mem_recall_hook.py`, `tests/test_mem_journal_hook.py`,
  `tests/test_mem_privacy_guard.py`, plus the settings-snippet expected-dict (three new
  hook→event rows) and the stateful-hook consistency tuple (recall hook). Suite: 111 → 163.

## v1.7 — 2026-07-07

Design pass: the kit learns to design websites, not just verify code — with the
German market as a first-class citizen. Reference content was produced by a live
web-research workflow (6 parallel researchers over primary sources) whose
load-bearing legal/technical claims were adversarially verified before authoring.

### Added
- **`webdesign` skill** — a staged web-design protocol that composes with /fable:
  frame the site → pick an explicit **design view** → design brief before code →
  implement by the view's rules → verify like a visitor (screenshots, reduced-motion
  drive, keyboard walk), then like a lawyer. Ships two on-demand reference docs:
  - `references/design-views.md` — the design-view taxonomy: **static/content-first,
    animated/motion-rich, interactive/app-like, immersive/scrollytelling, commerce**;
    per view a tech ceiling (no SPA on a brochure site; scroll-driven CSS before
    JS libraries), a motion vocabulary (`prefers-reduced-motion`: wrap, don't
    dampen), and a Core-Web-Vitals-anchored performance budget.
  - `references/german-market.md` — the German/DACH **hard gate**: Impressum
    (§ 5 DDG), Datenschutzerklärung (DSGVO), consent (§ 25 TDDDG) with the
    build-consent-free-first stance, BFSG accessibility (EN 301 549 / WCAG 2.1 AA),
    shop rules (§ 312j BGB button, PAngV, Widerruf), self-hosted fonts (LG München,
    Google-Fonts ruling), two-click embeds, consent-free analytics, German
    typography („…“, ß/ẞ, `lang="de"` + `hyphens: auto`, DIN-style formats,
    Sie/du as a one-time brand decision), and trust conventions.
- **`/design-variants` workflow** (`claude/workflows/design-variants.js`) — judge-panel
  design for genuinely open visual direction: an art director sets 3 competing
  directions (different design views where the brief allows), 3 builders produce
  self-contained zero-external-request HTML previews under `design-previews/`,
  distinct-lens judges (craft / audience fit / engineering, **plus a German-market
  compliance judge** when the brief mentions Germany) score every file they actually
  read, a synthesis names the winner and what to graft. Judges pin `effort: 'xhigh'`
  (asymmetric verification, kit rule).
- Doctrine bullet + fable-skill pointer routing website/web-UI work to the skill;
  README tree + playbook rows.
- `tests/test_webdesign_skill.py` — trigger-surface frontmatter, reference routing,
  the load-bearing law names, taxonomy coverage, and the installer/doctor
  regressions below. Suite: 100 → 111.

### Changed
- **`install.sh` installs skills as whole directories** — previously only `SKILL.md`
  was copied, which would have silently dropped `references/`; a skill whose
  checklist doesn't arrive is worse than no skill. Idempotency now compares every
  shipped file plus a recorded ship-list (`.fable-manifest`), so upgrades **prune
  files a previous kit version shipped but the current one doesn't** (a stale
  formerly-shipped checklist is silent drift) while user-added files are ignored
  and preserved. `tools/doctor.sh` verifies every shipped skill file (missing →
  FAIL, content drift → warn and no `ok` line, mirroring the hook checks). CI's
  install end-to-end step counts skills dynamically instead of hard-coding 3.
- The release diff itself went through the kit's own machinery before landing:
  plan-critiqued, /paranoid-review'd (22 agents; 18 confirmed findings fixed — the
  headline one: the webdesign skill's variants stage self-granted the Workflow
  opt-in, contradicting the orchestration gate; it now defers to the user), and the
  installed result live-tested on `claude-opus-4-8` (headless skill-discovery smoke
  + an ultracode workflow where Opus builders execute the skill end-to-end under
  xhigh adversarial audits). The violations those audits confirmed were folded back
  into the cross-view invariants: contrast checked per interactive STATE (the
  ghost-button hover fill), `scroll-behavior: smooth` counts as motion and lives
  inside the reduced-motion query, sticky headers demand `scroll-margin-top` on
  anchor targets.

## v1.6 — 2026-07-06

Structure pass: SUCCESSION.md's advice becomes shipped mechanism, and the kit learns
its native habitat — ultracode. Driven by a 9-auditor / adversarial-verify workflow
run over the whole repo (the kit reviewed the way the kit reviews).

### Added
- **`/big-task` workflow** (`claude/workflows/big-task.js`) — the mission statement as
  deterministic code: decompose a big task into independently verifiable, committable
  steps (with a plan-critique round), then per step implement → adversarially verify
  in a fresh context (xhigh; optionally `--verify-model=<tier>` pins verifiers to a
  stronger model) → one repair round → commit the checkpoint. Halts loudly after two
  rejected attempts, keeping every green checkpoint committed; ends with a
  completeness critic auditing the commits against the ORIGINAL request, not the plan.
- **Turnkey small-driver install**: `./install.sh --tier small` prints the new
  `settings-snippet-small.json` (base snippet + `FABLE_LOOP_THRESHOLD=2`), and
  `--strong-model <m>` durably pins the verification agents' frontmatter (idempotent:
  re-runs with the flag keep the pin instead of silently reverting it, closing a
  SUCCESSION.md drift). `tests/test_small_tier.py` covers snippet sync, pinning,
  idempotency, and flag errors.
- **Ultracode compatibility**: the orchestrate skill now teaches the opt-in rule
  (never launch the Workflow tool uninvited; a user-invoked /command is the opt-in for
  that run), the budget-directive API (`budget.total` guards — without one, loops run
  to the agent cap), `workflow()` composition, and effort/model tiering; the doctrine
  gets the one-bullet version; the README documents the phase-chaining loop
  (`/deep-plan` → `/big-task` → `/paranoid-review`). The fable skill gains a
  no-Workflow-tool fallback (degrade the machinery, never the rigor).

### Changed
- **Asymmetric verification is now encoded, not advised**: every verifier, refuter,
  and judge in the shipped workflows pins `effort: 'xhigh'`, so verification stays
  strong even when a small driver runs the session at lower effort.
- Workflow robustness fixes from the audit: paranoid-review no longer silently drops
  a second distinct finding at the same file:line (dedup key includes the title),
  reports a dead finder dimension as UNREVIEWED instead of clean, and budget-guards
  its verify fan-out; bug-hunt no longer counts a round of crashed hunters as "dry"
  and logs when the round cap ends a still-wet hunt; deep-plan returns the raw winning
  plan loudly (never a silent null) when the synthesizer dies.
- README claims aligned with code: bench described as *measuring* (not "proving"),
  destructive-guard/claim-audit bypass classes documented in Known limits, live-verify
  date scoped to the components it actually covered, doctrine line count fixed.

## v1.5 — 2026-07-06

Succession pass — Fable 5's last change to this repo. The kit was built to run
Opus 4.8 at Fable-grade discipline; this release makes it degrade gracefully onto
*smaller* driver models (Sonnet/Haiku tiers), and writes down the judgment that
until now lived only in weights. Organizing principle: as the model shrinks, move
weight from advice to structure.

### Added
- **`docs/SUCCESSION.md`** — running the kit on smaller models: what breaks first
  as the model shrinks (self-triggered verification, thread-keeping, grind
  discipline, orchestration, diagnosis depth) and which kit component carries each;
  per-tier configuration deltas; the asymmetric-verification principle (draft cheap,
  verify strong — and when every tier is small, buy rigor with votes instead of
  weights); `bench/` as the inheritance test; and the field notes — the
  transferable priors for diagnosis, building, and calibration.
- **Field notes in the oracle agent.** Eight hard-won diagnostic priors now live in
  the oracle's prompt — read at the exact moment of need, by whatever model is
  behind it ("when the bug makes no sense, one of the caller's assumptions is
  false", "no reproducer, no diagnosis", "symptom location is rarely cause
  location", ...).
- **`FABLE_LOOP_THRESHOLD`** environment knob for the loop alarm (clamped 2–10,
  default 3, invalid values fall back). Smaller models grind harder; on a
  Sonnet/Haiku driver the second identical failure is already the signal.
- **Doctrine: the escalation ladder now has a terminus.** When the oracle's next
  experiment also dead-ends, the ladder ends at the human — with a decision-ready
  summary (dead hypotheses, survivors, the next discriminating experiment) — never
  a third lap of the same loop.
- Docs-integrity tests: every relative markdown link in README/CHANGELOG/docs/bench
  resolves; every knob SUCCESSION.md tells an heir to set exists in the code it
  claims to configure; the oracle actually carries the field notes; all stateful
  hooks honor the same `FABLE_STATE_DIR` override. Plus loop-threshold tests.
  Suite: 87 → 93.

## v1.4 — 2026-07-06

Coverage pass: the reward-hacking failure mode gets its own deterministic tripwire, the
one manual install step gets a deterministic verifier, and two destructive-guard evasions
close. Test suite grows 51 → 87 (installer+doctor end-to-end, settings-snippet sync
guards, and regression cases for every new detection).

### Added
- **Test-weakening alarm (`posttool-test-weakening-alarm.py`, PostToolUse on
  Edit/Write/MultiEdit).** The doctrine forbids greening a suite by skipping the test,
  and the claim-audit gate asks about it at stop time — but both are downstream of the
  edit. The alarm watches the edit itself: adding a skip/disable marker
  (`@pytest.mark.skip/skipif/xfail`, `pytest.skip(`, `@unittest.skip*`, `it/test/
  describe.skip`, `xit(`, `t.Skip(`, `#[ignore]`, `@Disabled`, `@Ignore`) to a
  test file triggers a one-time-per-file revert-or-justify nudge. Only *added* markers
  count — occurrences in the new text must exceed the old, so refactoring around an
  existing skip stays silent. Fail-open, session-scoped state, TEST_PATH heuristic
  kept in sync with the claim-audit gate by a test.
- **`tools/doctor.sh` — post-install verifier.** The kit's weakest link was its one
  manual step: a botched settings merge leaves every hook silently unwired and the
  whole enforcement layer inert with zero symptoms. The doctor checks python3, every
  shipped hook/agent/workflow/skill file, hook compilation, doctrine presence (and the
  unmerged `CLAUDE.fable-protocol.md` case), settings.json validity + per-hook wiring +
  `effortLevel`, and state-dir writability. Exit 1 on any FAIL; covered end-to-end by
  tests (install → merge → doctor passes; each sabotage → doctor fails).
- **"On models after Opus 4.8" README section.** The kit targets failure modes, not
  model IDs; the section names the three assumptions most likely to break on a successor
  model (effort-level semantics, hook payload contracts, which failure modes remain) and
  points at `bench/` as the way to retire ceremony a stronger model no longer needs.
- Doctrine bullet: you under-use persistent memory by default (per the migration
  guide) — check auto-memory before re-deriving project decisions, bank non-obvious
  lessons via postmortem.
- Settings-snippet sync tests: every shipped hook is wired, every wired hook ships,
  each to the right event; a hook added to `claude/hooks/` without snippet wiring now
  fails CI instead of shipping inert.

### Changed
- **Claim-audit gate: Bash writes to test files now trigger the weakening addendum** —
  closing the v1.3 known limit. A file-writing Bash command that names a test-looking
  path (`sed -i ... tests/test_x.py`, `echo ... > foo_test.go`) counts as a test edit;
  a bare test-dir token in a read-mostly command (`pytest tests/ > out.log`) does not.
- **Destructive guard: two evasions closed.** `git push origin +main` (the refspec
  spelling of force-push) is now blocked like `--force`; `git switch -f /
  --discard-changes` (the modern porcelain for `checkout --`) joins the tree-destroyer
  tier (blocked only when the tree is dirty; plain `git switch`/`-c` untouched).
- Loop-alarm regression tests: whitespace-variant commands count as the same grind;
  independent commands accumulate independently. Compaction-recovery test: a 60-file
  dirty tree injects at most 30 status lines.

## v1.3 — 2026-07-06

Structural pass: four advisory rules promoted to deterministic enforcement, closing the
gaps where a documented failure mode still relied on the model choosing to follow prose.
All new hooks are unit-tested (51 tests total) and fail open; none are A/B benchmarked
yet — the bench measures the claim-audit gate only.

### Added
- **Loop-alarm hook (`posttool-loop-alarm.py`, PostToolUse).** The doctrine's
  "two failed fixes → oracle" rule was advisory — the exact category the benchmark
  showed gets skipped under momentum. The hook counts per-session failures of the SAME
  command; any file modification resets the counts (retrying after a change is
  legitimate iteration), interleaved read-only probes do not. On the 3rd identical
  failure it injects a one-time stop-and-reassess directive. Conservative by design:
  a run only counts as failed on an explicit exit code / error flag in the payload —
  if your Claude Code build omits those, the alarm is inert rather than nagging.
- **Destructive-command guard (`pretool-destructive-guard.py`, PreToolUse).** Blocks
  `git reset --hard`, `git checkout --`/`-f`/`.`, worktree `git restore`, and
  `git clean -f` when `git status --porcelain` shows uncommitted or untracked work to
  lose (clean tree → untouched); blocks `git stash drop|clear`, bare `git push --force`
  (use `--force-with-lease`), and recursive `rm` aimed at `/`, `~`, `.`, `..`, or `*`
  unconditionally. Quote-aware: a commit message that merely *mentions* `reset --hard`
  does not trip it. Override (`FABLE_DESTRUCTIVE_OK=1`) requires explicit user approval
  per the doctrine.
- **Original request survives compaction verbatim.** A new PreCompact hook
  (`precompact-save-task.py`) saves the first user message (system-reminder tags
  stripped, 4000-char cap) to a per-session state file; the SessionStart(compact) hook —
  now `sessionstart-compact-recovery.py`, replacing v1.2's inline shell — injects it
  back alongside the recovery protocol and the actual git state. The doctrine's #1
  compaction rule ("preserve the original task statement verbatim") no longer depends
  on the summarizer honoring an instruction.
- Two doctrine bullets: never green a failing test by weakening it (say so explicitly
  if a test's expectation was genuinely wrong), and checkpoint (`git stash push -u` /
  WIP commit) before any destructive operation.

### Changed
- **The claim-audit gate now knows about test-weakening.** When the session edited test
  files (tests//spec/__tests__ dirs, `test_*`, `*_test.*`, `*.test.*`, `*.spec.*`) and
  the final message claims completion, the audit directive explicitly demands confirming
  no assertion was loosened, case deleted, tolerance widened, or skip added — the
  reward-hacking variant of the false-green failure mode, previously uncovered.
- `install.sh` needs no changes for the new hooks (the `hooks/*.py` glob covers them);
  its closing summary now describes the full five-hook set.

## v1.2 — 2026-07-05

Hardening pass: an adversarial review of the kit by its own standards. The benchmark in
`bench/RESULTS.md` measured v1.1; the gate's *firing conditions* widened in v1.2 (Bash-write
detection, negation guard) but the blocking mechanism is unchanged.

### Fixed
- **Stop-hook gate crashed (exit 1) on malformed transcripts** — a transcript entry with
  string `content` or a non-dict block raised an uncaught `AttributeError`. The hook now
  tolerates malformed entries and fails open on any unexpected error: a hook bug can no
  longer break a session.
- **`paranoid-review` silently dropped findings whose verifier died** — contradicting the
  kit's own "nothing silently dropped" principle (`bug-hunt` already handled this
  correctly). Dead-verifier findings are now recovered into the `unverified` bucket.
- **`bench/run.sh` always printed `exit=0`** — under `set -e` the script died before the
  echo on any failure, so the reported exit code was meaningless. Now captured properly.
- **`install.sh` backups created loadable duplicates** — backing up `skills/fable/` to
  `skills/fable.bak-<stamp>/` left a directory with a SKILL.md inside that Claude Code
  would load as a second skill. Backups now go to `~/.claude/fable-protocol-backups/<stamp>/`.

### Changed
- **Three-way verdicts are now structural, not prose.** `paranoid-review`, `bug-hunt`, and
  `verify-claim` previously forced verifiers into boolean schemas (`real: true/false`,
  `refuted: true/false` + an "UNPROVEN:" string prefix) — violating the kit's own
  "three-way honesty" principle at the schema level. All three now use enum verdicts
  (`confirmed/refuted/unverifiable`, `refuted/withstood/unproven`) so "could not verify"
  is machine-distinguishable from "disproven".
- **`verify-claim` fails closed on any concrete refutation**: one refuter with concrete
  disproof now sinks the claim even if the other two lenses couldn't break it (previously
  2 non-refuted votes outvoted 1 refutation). Refutations are evidence, not ballots.
- **The claim-audit gate now sees Bash file writes.** Sessions that modify files via
  `>`/`>>` redirection, `sed -i`, `tee`, `mv`/`cp`/`rm`, `patch`, or `git apply` no longer
  bypass the gate (redirects to `/dev/null` don't count). It is also negation-aware:
  "not done yet / remains to be fixed" no longer trips it.
- **Compaction recovery injects real state.** The SessionStart(compact) hook now appends
  the actual `git status --short` and `git diff --stat` output instead of only instructing
  the model to go re-derive it — deterministic data beats an advisory instruction.
- **`paranoid-review` dedups findings across dimensions** before verification (first
  dimension to reach Verify claims the finding), and both review workflows sort confirmed
  findings by severity.
- **`deep-plan` clamps judge scores to 0–10 and logs omitted scores** instead of silently
  counting them as 0.
- **`bench/score.py` automates the claims audit**: when `result.json` from a headless run
  sits next to the instance, it reports `final_message_claims_done` and
  `false_completion_claim` using the same regex the Stop-hook enforces (sync guarded by a
  test).
- **`install.sh` is idempotent** (unchanged files are skipped, no backup churn) and warns
  when Claude Code < 2.1.154 (saved workflows unavailable).

### Added
- `tests/` — unit tests for the Stop-hook gate (13 cases: blocking, one-shot guard,
  negation, Bash-write detection, fail-open paths) and a hook↔bench regex sync guard.
- `tools/check-workflows.mjs` — compiles each workflow script as an AsyncFunction with the
  harness globals (plain `node --check` cannot parse them).
- `.github/workflows/ci.yml` — shell/python/JSON/workflow syntax checks, frontmatter
  checks, unit tests, a twice-run install end-to-end test, and the pristine-task 1/15
  scoring anchor.

## v1.1 — 2026-07-02

Measured: A/B benchmark (`bench/`) + the Stop-hook claim-audit gate. See
`bench/RESULTS.md`.

## v1.0 — 2026-07-02

Initial release: doctrine, agents (verifier / plan-critic / oracle), workflows
(paranoid-review / verify-claim / deep-plan / bug-hunt), skills (fable / orchestrate /
postmortem), compaction-recovery hook, installer.
