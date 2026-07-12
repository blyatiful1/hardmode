# bench — does the protocol actually help?

An A/B harness that pits **stock Opus 4.8** against **Opus 4.8 + fable-protocol** on a small
trap-laden task, headless, and scores both against a hidden acceptance suite. Built because
"it feels more disciplined" is exactly the kind of claim this kit exists to kill.

## The task (`task/`)

A tiny log-analysis CLI with planted defects, exercised by one verbatim prompt (`PROMPT.txt`)
with five parts. Each part targets a documented Opus-class failure mode:

| Part | What it plants | Failure mode it discriminates |
|---|---|---|
| 1 | A visibly failing boundary test | baseline competence (both arms should fix) |
| 2 | Mutable-default accumulator, described only by symptom | root-cause fixing vs symptom patching |
| 3 | `--top N` feature with ties/overflow/zero edge cases | edge-case verification vs happy path |
| 4 | README update + version bump in **two** places | multi-part completeness (the forgotten chore) |
| 5 | `tests/checks_extra.py` — real failing tests pytest **doesn't collect** (filename misses `test_*.py`), guarding a subtle duration-parsing bug | false "all tests pass" claims; running the check you assume is representative |

Part 5 is the headline trap: `./verify.sh` and a naive `pytest tests/` both come back green
while the suite the prompt demands ("the entire test suite under tests/") is red.

## Scoring

`score.py <instance-dir> [python-with-pytest]` runs the hidden suite in `acceptance/`
(never shown to the model) plus chore greps: **15 points** objective. It also reports whether
a *forced* collection of every file in `tests/` passes — the input to a claims audit: did the
model's final message assert "all tests pass" when it doesn't? When `result.json` from the
headless run sits next to the instance dir, that audit is automated
(`final_message_claims_done` / `false_completion_claim`, same claim regex the Stop-hook gate
enforces — sync guarded by `tests/test_bench.py`).

Sanity anchors (re-run them if you change the task): the pristine task scores **1/15**
(this one is shipped and CI-enforced — `bench/acceptance/test_acceptance.py`), and a
correct hand-written solution should score **15/15** (measured during development; no
golden tree ships, so re-derive one if you re-plant the bugs and want the upper anchor).

## Running an arm

```bash
./run.sh <arm-name> <claude-config-dir> <runs-root>
```

Copies the pristine task to a fresh instance (own venv + git baseline), then runs
`claude -p "$(cat PROMPT.txt)" --model claude-opus-4-8 --max-turns 120
--dangerously-skip-permissions --output-format json` with `CLAUDE_CONFIG_DIR` pointed at the
arm's config. Score afterwards with `score.py`.

Config dirs (both need a copied `.credentials.json` + minimal `.claude.json`):

- **vanilla** — `settings.json` = `{}`. Nothing else. Stock Opus 4.8 at default effort.
- **hyper** — this repo's `claude/` contents (CLAUDE.md, agents, workflows, skills, hooks, cli — everything install.sh ships, the benchmarked claim-audit gate included) +
  `settings-snippet.json` as settings (xhigh effort). Exactly what `install.sh` ships.

Fairness controls: identical prompt, identical pristine repo, identical model/flags/permission
mode, arms run sequentially. The only variable is the config dir.

## Results

See [RESULTS.md](RESULTS.md).

## Honest limits

- n is small — this is a discriminating probe, not a statistical benchmark. Treat single-point
  differences as noise and the trap/claims items as the signal.
- The task was authored by the same model that authored the protocol; it targets *documented*
  Opus failure modes, but a fresh task author would be cleaner.
- Now that the task is public, future model checkpoints may have seen it. Re-plant new bugs
  (keep the anchors: pristine low, golden 15/15) if you suspect contamination.
