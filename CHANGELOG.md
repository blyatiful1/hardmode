# Changelog

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
