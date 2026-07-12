#!/usr/bin/env bash
# fable-protocol installer — copies the framework into ~/.claude with backups.
# Never edits settings.json; prints the snippet to merge instead.
#
# Flags (both optional, for small driver models — see docs/SUCCESSION.md):
#   --tier small          print the small-driver settings snippet (FABLE_LOOP_THRESHOLD=2)
#   --strong-model <m>    pin the verification agents (verifier, oracle, plan-critic)
#                         to model <m>, e.g. --strong-model opus — draft cheap, verify strong
set -euo pipefail

TIER="opus"
STRONG_MODEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="${2:?--tier needs a value (small|opus)}"; shift 2 ;;
    --strong-model) STRONG_MODEL="${2:?--strong-model needs a model name, e.g. opus}"; shift 2 ;;
    -h|--help) awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)"; exit 1 ;;
  esac
done
case "$TIER" in small|opus) ;; *) echo "unknown --tier: $TIER (small|opus)"; exit 1 ;; esac

SRC="$(cd "$(dirname "$0")/claude" && pwd)"
DST="${CLAUDE_DIR:-$HOME/.claude}"
STAMP="$(date +%Y%m%d-%H%M%S)"
# Backups live OUTSIDE the live agents/skills/... trees: a fable.bak-*/ directory
# left inside skills/ would itself be loaded by Claude Code as a duplicate skill.
BAK="$DST/fable-protocol-backups/$STAMP"

# backup <target> <relative-name> — copy the existing target into the backup dir
# (the original stays in place; the copy is the safety net before it is overwritten).
backup() {
  [ -e "$1" ] || return 0
  mkdir -p "$BAK/$(dirname "$2")"
  cp -r "$1" "$BAK/$2"
  echo "  backed up: $1 -> $BAK/$2"
}

# identical <src> <dst> — true if dst exists and matches src (skip needless backups).
identical() { [ -f "$2" ] && cmp -s "$1" "$2"; }

# skill_unchanged <src_dir> <dst_dir> — true if every file the repo ships for this
# skill already matches the destination AND the recorded ship-list (.fable-manifest)
# is current. Files a USER added are ignored (and preserved); files a PREVIOUS kit
# version shipped are tracked in the manifest so upgrades can prune them — a stale
# formerly-shipped checklist sitting next to the current one is silent drift.
skill_unchanged() {
  local f rel
  [ -f "$2/.fable-manifest" ] || return 1
  diff -q <(cd "$1" && find . -type f | LC_ALL=C sort) "$2/.fable-manifest" >/dev/null 2>&1 || return 1
  while IFS= read -r -d '' f; do
    rel="${f#"$1"/}"
    cmp -s "$f" "$2/$rel" || return 1
  done < <(find "$1" -type f -print0)
  return 0
}

# prune_stale_skill_files <src_dir> <dst_dir> — remove files the manifest says a
# previous kit version shipped but this version no longer does. User files (never
# in a manifest) are untouched. Runs after backup, so nothing is unrecoverable.
prune_stale_skill_files() {
  local rel
  [ -f "$2/.fable-manifest" ] || return 0
  while IFS= read -r rel; do
    rel="${rel#./}"
    [ -n "$rel" ] || continue
    [ -f "$1/$rel" ] || rm -f "$2/$rel"
  done < "$2/.fable-manifest"
}

# render_agent <src> — agent markdown to stdout, with a `model:` pin injected into the
# frontmatter when --strong-model was given (asymmetric verification: draft cheap,
# verify strong). Skips injection if the frontmatter already pins a model.
render_agent() {
  if [ -n "$STRONG_MODEL" ] && ! awk '/^---$/{n++; next} n==1 && /^model:/{found=1} END{exit !found}' "$1"; then
    awk -v m="$STRONG_MODEL" 'NR>1 && /^---$/ && !done { print "model: " m; done=1 } { print }' "$1"
  else
    cat "$1"
  fi
}

echo "Installing fable-protocol into $DST${STRONG_MODEL:+ (verification agents pinned to model: $STRONG_MODEL)}"
mkdir -p "$DST/agents" "$DST/workflows" "$DST/skills" "$DST/hooks"

TMP_AGENT="$(mktemp)"
trap 'rm -f "$TMP_AGENT"' EXIT
for f in "$SRC"/agents/*.md; do
  t="$DST/agents/$(basename "$f")"
  render_agent "$f" > "$TMP_AGENT"
  identical "$TMP_AGENT" "$t" && { echo "  agent:    $(basename "$f") (unchanged)"; continue; }
  backup "$t" "agents/$(basename "$f")"; cp "$TMP_AGENT" "$t"; echo "  agent:    $(basename "$f")"
done
for f in "$SRC"/workflows/*.js; do
  t="$DST/workflows/$(basename "$f")"
  identical "$f" "$t" && { echo "  workflow: /$(basename "$f" .js) (unchanged)"; continue; }
  backup "$t" "workflows/$(basename "$f")"; cp "$f" "$t"; echo "  workflow: /$(basename "$f" .js)"
done
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"; t="$DST/skills/$name"
  skill_unchanged "${d%/}" "$t" && { echo "  skill:    $name (unchanged)"; continue; }
  backup "$t" "skills/$name"; prune_stale_skill_files "${d%/}" "$t"
  mkdir -p "$t"; cp -r "${d%/}"/. "$t"/
  (cd "${d%/}" && find . -type f | LC_ALL=C sort) > "$t/.fable-manifest"
  echo "  skill:    $name"
done
for f in "$SRC"/hooks/*.py; do
  t="$DST/hooks/$(basename "$f")"
  identical "$f" "$t" && { echo "  hook:     $(basename "$f") (unchanged)"; continue; }
  backup "$t" "hooks/$(basename "$f")"; cp "$f" "$t"; chmod +x "$t"; echo "  hook:     $(basename "$f")"
done

# mem CLI + memory corpus — a NEW component KIND (not an agent/workflow/skill/hook), so
# it needs its own copy block. mem.py is a single file → flat identical() idempotency +
# chmod +x, same as a hook. privacy.toml is the USER'S pattern file: seed it only when
# absent, NEVER overwrite work-markers the user has tuned (unlike the code, it is data
# the user owns). Both go OUTSIDE the backup tree per the same rule as everything else.
mkdir -p "$DST/cli" "$DST/memory"
t="$DST/cli/mem.py"
if identical "$SRC/cli/mem.py" "$t"; then
  echo "  cli:      mem.py (unchanged)"
else
  backup "$t" "cli/mem.py"; cp "$SRC/cli/mem.py" "$t"; chmod +x "$t"; echo "  cli:      mem.py"
fi
if [ -e "$DST/memory/privacy.toml" ]; then
  echo "  memory:   privacy.toml (kept — your patterns are never overwritten)"
else
  cp "$SRC/memory/privacy.toml" "$DST/memory/privacy.toml"
  echo "  memory:   privacy.toml (seeded — edit it to add your own work-markers)"
fi

# Bootstrap the memory index ONCE, now — so the first SessionEnd journal hook never has
# to carry a cold full build inside its 10s budget (a killed cold build rolls back to
# empty and recall silently never works). Runs under CLAUDE_DIR="$DST" so it indexes the
# install target, not the runner's $HOME. Soft-fail: a missing python3 must not abort.
if command -v python3 >/dev/null 2>&1; then
  if CLAUDE_DIR="$DST" python3 "$DST/cli/mem.py" index --rebuild >/dev/null 2>&1; then
    echo "  index:    memory corpus indexed (mem index --rebuild)"
  else
    echo "  WARNING: initial 'mem index --rebuild' failed — recall warms up on first SessionEnd."
  fi
else
  echo "  NOTE: 'python3' not found — skipped initial memory index; run"
  echo "        'CLAUDE_DIR=\"$DST\" python3 \"$DST/cli/mem.py\" index --rebuild' once python3 is installed."
fi

# CLAUDE.md: never clobber an existing doctrine
if [ -e "$DST/CLAUDE.md" ]; then
  if identical "$SRC/CLAUDE.md" "$DST/CLAUDE.md"; then
    echo "  doctrine: CLAUDE.md (unchanged)"
  else
    cp "$SRC/CLAUDE.md" "$DST/CLAUDE.fable-protocol.md"
    echo "  NOTE: $DST/CLAUDE.md already exists — wrote CLAUDE.fable-protocol.md next to it; merge manually."
  fi
else
  cp "$SRC/CLAUDE.md" "$DST/CLAUDE.md"
  echo "  doctrine: CLAUDE.md (edit the '## This machine' section for your box)"
fi

# Soft version check: saved workflows need Claude Code >= 2.1.154.
if command -v claude >/dev/null 2>&1; then
  ver="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  if [ -n "$ver" ] && [ "$(printf '%s\n' "2.1.154" "$ver" | sort -V | head -1)" != "2.1.154" ]; then
    echo
    echo "  WARNING: Claude Code $ver detected; saved workflows (/paranoid-review etc.)"
    echo "  need >= 2.1.154. Everything else in the kit still works."
  fi
else
  echo
  echo "  NOTE: 'claude' not found on PATH — could not verify Claude Code >= 2.1.154."
fi

SNIPPET="$SRC/settings/settings-snippet.json"
[ "$TIER" = "small" ] && SNIPPET="$SRC/settings/settings-snippet-small.json"
echo
echo "Last step (manual): merge this into $DST/settings.json:"
echo "----------------------------------------------------------------"
cat "$SNIPPET"
echo "----------------------------------------------------------------"
if [ "$TIER" = "small" ]; then
  echo "Small-driver tier (docs/SUCCESSION.md): FABLE_LOOP_THRESHOLD=2 — on a small model"
  echo "the SECOND identical failure is already the signal. Prefer the scripted workflows"
  echo "over free-form delegation, and run big work as /big-task <task> (checkpointed"
  echo "steps, adversarial verify, commit every green)."
  if [ -z "$STRONG_MODEL" ]; then
    echo "TIP: re-run with --strong-model <strongest tier your plan offers> to pin the"
    echo "verification agents — draft cheap, verify strong. Never let the checker be"
    echo "weaker than the drafter on work that matters."
  fi
fi
echo "effortLevel xhigh is the single biggest lever on Opus 4.8. The hook set:"
echo "  Stop         claim-audit gate (benchmarked: bench/RESULTS.md)"
echo "  PreCompact + SessionStart(compact)  save/inject the original request verbatim"
echo "               plus the actual git state after every compaction"
echo "  PreToolUse   destructive-command guard (protects uncommitted work)"
if [ "$TIER" = "small" ]; then
  echo "  PostToolUse  loop alarm (2nd identical failing command -> stop and reassess)"
else
  echo "  PostToolUse  loop alarm (3rd identical failing command -> stop and reassess)"
fi
echo "  PostToolUse  test-weakening alarm (skip/disable marker added to a test file)"
echo "  UserPromptSubmit  cross-project memory recall (read-only mem CLI FTS query)"
echo "  SessionEnd   session journal breadcrumb + incremental memory re-index"
echo "  PreToolUse   memory privacy guard (blocks work-markers leaking into the global corpus)"
echo "The mem CLI (cross-project memory, layered on native auto-memory):"
echo "  python3 ~/.claude/cli/mem.py search|show|stats|doctor|gc-scan  (corpus: ~/.claude/memory/)"
echo "CLAUDE_CODE_MAX_OUTPUT_TOKENS is best-effort (harmless; clamped per model)."
echo
echo "After merging, verify the install deterministically:"
echo "  ./tools/doctor.sh"
echo
echo "Done. Start a new Claude Code session and ask: 'quote the first bullet of your"
echo "Evidence before claims doctrine' to confirm the load."
