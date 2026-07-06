# Changelog

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
