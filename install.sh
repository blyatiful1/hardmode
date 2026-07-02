#!/usr/bin/env bash
# fable-protocol installer — copies the framework into ~/.claude with backups.
# Never edits settings.json; prints the snippet to merge instead.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/claude" && pwd)"
DST="${CLAUDE_DIR:-$HOME/.claude}"
STAMP="$(date +%Y%m%d-%H%M%S)"

backup() { [ -e "$1" ] && cp -r "$1" "$1.bak-$STAMP" && echo "  backed up: $1 -> $1.bak-$STAMP" || true; }

echo "Installing fable-protocol into $DST"
mkdir -p "$DST/agents" "$DST/workflows" "$DST/skills" "$DST/hooks"

# Agents + workflows: plain copies (backup on collision)
for f in "$SRC"/agents/*.md; do
  t="$DST/agents/$(basename "$f")"; backup "$t"; cp "$f" "$t"; echo "  agent:    $(basename "$f")"
done
for f in "$SRC"/workflows/*.js; do
  t="$DST/workflows/$(basename "$f")"; backup "$t"; cp "$f" "$t"; echo "  workflow: /$(basename "$f" .js)"
done
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"; t="$DST/skills/$name"; backup "$t"; mkdir -p "$t"; cp "$d/SKILL.md" "$t/SKILL.md"; echo "  skill:    $name"
done
for f in "$SRC"/hooks/*.py; do
  t="$DST/hooks/$(basename "$f")"; backup "$t"; cp "$f" "$t"; chmod +x "$t"; echo "  hook:     $(basename "$f")"
done

# CLAUDE.md: never clobber an existing doctrine
if [ -e "$DST/CLAUDE.md" ]; then
  cp "$SRC/CLAUDE.md" "$DST/CLAUDE.fable-protocol.md"
  echo "  NOTE: $DST/CLAUDE.md already exists — wrote CLAUDE.fable-protocol.md next to it; merge manually."
else
  cp "$SRC/CLAUDE.md" "$DST/CLAUDE.md"
  echo "  doctrine: CLAUDE.md (edit the '## This machine' section for your box)"
fi

echo
echo "Last step (manual): merge this into $DST/settings.json:"
echo "----------------------------------------------------------------"
cat "$SRC/settings/settings-snippet.json"
echo "----------------------------------------------------------------"
echo "effortLevel xhigh is the single biggest lever on Opus 4.8. The compact hook"
echo "adds deterministic post-compaction recovery. The Stop hook is the claim-audit"
echo "gate (benchmarked: bench/RESULTS.md). CLAUDE_CODE_MAX_OUTPUT_TOKENS is"
echo "best-effort (harmless; clamped per model)."
echo
echo "Done. Start a new Claude Code session and ask: 'quote the first bullet of your"
echo "Evidence before claims doctrine' to confirm the load."
