#!/usr/bin/env bash
# fable-protocol doctor — verifies an installation is actually live, not silently inert.
#
# The kit's weakest link is the one manual step: merging the settings snippet.
# A botched merge leaves every hook unwired and the whole kit inert with zero
# symptoms — the exact failure the kit exists to prevent. This script makes the
# check deterministic. Run it after ./install.sh (and after Claude Code updates).
#
# Exit 0 = installation verified; exit 1 = at least one FAIL line above.
set -uo pipefail

SRC="$(cd "$(dirname "$0")/../claude" && pwd)"
DST="${CLAUDE_DIR:-$HOME/.claude}"
fail=0
ok()   { echo "  ok:   $1"; }
bad()  { echo "  FAIL: $1"; fail=1; }
warn() { echo "  warn: $1"; }

echo "fable-protocol doctor — checking $DST"

# 1. python3 — every hook runs through it.
if command -v python3 >/dev/null 2>&1; then
  ok "python3 on PATH ($(python3 --version 2>&1))"
else
  bad "python3 not on PATH — every hook is inert"
fi

# 2. Every component the repo ships is installed (and hooks compile).
for f in "$SRC"/hooks/*.py; do
  t="$DST/hooks/$(basename "$f")"
  if [ ! -f "$t" ]; then
    bad "hook missing: $t (re-run ./install.sh)"
  elif ! python3 -m py_compile "$t" 2>/dev/null; then
    bad "hook does not compile: $t"
  elif ! cmp -s "$f" "$t"; then
    warn "hook differs from this repo checkout: $t (older kit version?)"
  else
    ok "hook: $(basename "$f")"
  fi
done
for f in "$SRC"/agents/*.md; do
  [ -f "$DST/agents/$(basename "$f")" ] && ok "agent: $(basename "$f")" \
    || bad "agent missing: $DST/agents/$(basename "$f")"
done
for f in "$SRC"/workflows/*.js; do
  [ -f "$DST/workflows/$(basename "$f")" ] && ok "workflow: /$(basename "$f" .js)" \
    || bad "workflow missing: $DST/workflows/$(basename "$f")"
done
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"; complete=1; drifted=0
  while IFS= read -r -d '' f; do
    rel="${f#"${d%/}"/}"
    if [ ! -f "$DST/skills/$name/$rel" ]; then
      bad "skill file missing: $DST/skills/$name/$rel"; complete=0
    elif ! cmp -s "$f" "$DST/skills/$name/$rel"; then
      warn "skill file differs from this repo checkout: $DST/skills/$name/$rel (older kit version?)"; drifted=1
    fi
  done < <(find "${d%/}" -type f -print0)
  [ "$complete" -eq 1 ] && [ "$drifted" -eq 0 ] && ok "skill: $name"
done

# 2b. The mem CLI is a NEW component KIND — none of the four globs above (hooks/agents/
# workflows/skills) cover claude/cli/, so it gets a hand-written check: file present,
# compiles, and its own self-diagnostic runs clean on a fresh (corpus-less) install,
# reporting its FTS mode (fts5 / degraded-like). The three mem hooks (recall, journal,
# privacy-guard) are ordinary claude/hooks/*.py and are ALREADY covered by the hooks
# glob above — do not re-check them here.
MEM="$DST/cli/mem.py"
if [ ! -f "$MEM" ]; then
  bad "mem CLI missing: $MEM (re-run ./install.sh)"
elif ! python3 -m py_compile "$MEM" 2>/dev/null; then
  bad "mem CLI does not compile: $MEM"
else
  out="$(CLAUDE_DIR="$DST" python3 "$MEM" doctor 2>/dev/null)"; rc=$?
  mode="$(printf '%s\n' "$out" | sed -n 's/^mode=//p')"
  if [ "$rc" -eq 0 ]; then
    ok "mem CLI (mode=${mode:-unknown})"
  else
    bad "mem CLI self-check failed: CLAUDE_DIR=$DST python3 $MEM doctor"
  fi
fi

# Memory corpus dir writable + privacy pattern seed present.
MEMDIR="$DST/memory"
if mkdir -p "$MEMDIR" 2>/dev/null && touch "$MEMDIR/.doctor-probe" 2>/dev/null; then
  rm -f "$MEMDIR/.doctor-probe"
  ok "memory dir writable: $MEMDIR"
else
  bad "memory dir not writable: $MEMDIR — recall + journal re-indexing will be inert"
fi
if [ -f "$MEMDIR/privacy.toml" ]; then
  ok "privacy.toml present"
else
  warn "privacy.toml missing in $MEMDIR — the privacy guard has no patterns to match (fails open)"
fi

# 3. Doctrine is loadable.
if grep -q "Evidence before claims" "$DST/CLAUDE.md" 2>/dev/null; then
  ok "doctrine present in CLAUDE.md"
  if grep -q "Replace with 3-6 lines" "$DST/CLAUDE.md" 2>/dev/null; then
    warn "the '## This machine' section is still the placeholder — fill it in"
  fi
elif [ -f "$DST/CLAUDE.fable-protocol.md" ]; then
  bad "doctrine NOT merged: it sits unloaded in CLAUDE.fable-protocol.md next to your CLAUDE.md"
else
  bad "doctrine missing: no Evidence-before-claims section in $DST/CLAUDE.md"
fi

# 4. The manual step: settings.json actually wires the hooks.
SETTINGS="$DST/settings.json"
if [ ! -f "$SETTINGS" ]; then
  bad "settings.json missing — no hooks are wired, the enforcement layer is OFF"
elif ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SETTINGS" 2>/dev/null; then
  bad "settings.json is not valid JSON — Claude Code will ignore it"
else
  ok "settings.json parses"
  for f in "$SRC"/hooks/*.py; do
    name="$(basename "$f")"
    if grep -q "$name" "$SETTINGS"; then
      ok "wired: $name"
    else
      bad "NOT wired in settings.json: $name (merge the snippet from install.sh)"
    fi
  done
  if python3 -c "
import json,sys
s = json.load(open(sys.argv[1]))
sys.exit(0 if s.get('effortLevel') == 'xhigh' else 1)" "$SETTINGS" 2>/dev/null; then
    ok "effortLevel: xhigh (the single biggest lever)"
  else
    warn "effortLevel is not 'xhigh' in settings.json — on Opus 4.8 this is THE lever"
  fi
fi

# 5. Hook state dir is writable (loop alarm, weakening alarm, compaction save).
STATE="${FABLE_STATE_DIR:-$DST/tmp/fable-protocol}"
if mkdir -p "$STATE" 2>/dev/null && touch "$STATE/.doctor-probe" 2>/dev/null; then
  rm -f "$STATE/.doctor-probe"
  ok "state dir writable: $STATE"
else
  bad "state dir not writable: $STATE — stateful hooks (loop alarm, compaction save) will be inert"
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "DOCTOR: FAILED — fix the FAIL lines above, then re-run."
  exit 1
fi
echo "DOCTOR: installation verified. Final live check (needs a real session):"
echo "  ask a fresh session to 'quote the first bullet of your Evidence before claims doctrine'."
