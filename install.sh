#!/usr/bin/env bash
# fable-protocol installer — copies the framework into ~/.claude with backups.
# Never edits settings.json; prints the snippet to merge instead.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/claude" && pwd)"
DST="${CLAUDE_DIR:-$HOME/.claude}"
STAMP="$(date +%Y%m%d-%H%M%S)"
# Backups live OUTSIDE the live agents/skills/... trees: a fable.bak-*/ directory
# left inside skills/ would itself be loaded by Claude Code as a duplicate skill.
BAK="$DST/fable-protocol-backups/$STAMP"

# backup <target> <relative-name> — move the existing target into the backup dir.
backup() {
  [ -e "$1" ] || return 0
  mkdir -p "$BAK/$(dirname "$2")"
  cp -r "$1" "$BAK/$2"
  echo "  backed up: $1 -> $BAK/$2"
}

# identical <src> <dst> — true if dst exists and matches src (skip needless backups).
identical() { [ -f "$2" ] && cmp -s "$1" "$2"; }

echo "Installing fable-protocol into $DST"
mkdir -p "$DST/agents" "$DST/workflows" "$DST/skills" "$DST/hooks"

for f in "$SRC"/agents/*.md; do
  t="$DST/agents/$(basename "$f")"
  identical "$f" "$t" && { echo "  agent:    $(basename "$f") (unchanged)"; continue; }
  backup "$t" "agents/$(basename "$f")"; cp "$f" "$t"; echo "  agent:    $(basename "$f")"
done
for f in "$SRC"/workflows/*.js; do
  t="$DST/workflows/$(basename "$f")"
  identical "$f" "$t" && { echo "  workflow: /$(basename "$f" .js) (unchanged)"; continue; }
  backup "$t" "workflows/$(basename "$f")"; cp "$f" "$t"; echo "  workflow: /$(basename "$f" .js)"
done
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"; t="$DST/skills/$name"
  identical "$d/SKILL.md" "$t/SKILL.md" && { echo "  skill:    $name (unchanged)"; continue; }
  backup "$t" "skills/$name"; mkdir -p "$t"; cp "$d/SKILL.md" "$t/SKILL.md"; echo "  skill:    $name"
done
for f in "$SRC"/hooks/*.py; do
  t="$DST/hooks/$(basename "$f")"
  identical "$f" "$t" && { echo "  hook:     $(basename "$f") (unchanged)"; continue; }
  backup "$t" "hooks/$(basename "$f")"; cp "$f" "$t"; chmod +x "$t"; echo "  hook:     $(basename "$f")"
done

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

echo
echo "Last step (manual): merge this into $DST/settings.json:"
echo "----------------------------------------------------------------"
cat "$SRC/settings/settings-snippet.json"
echo "----------------------------------------------------------------"
echo "effortLevel xhigh is the single biggest lever on Opus 4.8. The compact hook"
echo "injects deterministic post-compaction recovery (protocol + actual git state)."
echo "The Stop hook is the claim-audit gate (benchmarked: bench/RESULTS.md)."
echo "CLAUDE_CODE_MAX_OUTPUT_TOKENS is best-effort (harmless; clamped per model)."
echo
echo "Done. Start a new Claude Code session and ask: 'quote the first bullet of your"
echo "Evidence before claims doctrine' to confirm the load."
