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

# crlf_same <a> <b> — content-equal after normalizing CRLF/LF (autocrlf makes the
# installed copy and the repo checkout differ on line endings without real drift;
# install.ps1 also rewrites agents to LF). Reports staleness as a warn, not a FAIL.
crlf_same() { [ -f "$2" ] && cmp -s <(tr -d '\r' <"$1") <(tr -d '\r' <"$2"); }
# agent_same — like crlf_same but also ignores an installer-injected `model:`
# frontmatter pin (--strong-model), so a pinned install is not misreported as drift.
agent_same() { [ -f "$2" ] && cmp -s <(sed '/^model: /d' "$1" | tr -d '\r') <(sed '/^model: /d' "$2" | tr -d '\r'); }

echo "fable-protocol doctor — checking $DST"

# 0. Claude Code version — saved workflows (/paranoid-review etc.) need >= 2.1.154.
if command -v claude >/dev/null 2>&1; then
  ver="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  if [ -n "$ver" ] && [ "$(printf '%s\n' "2.1.154" "$ver" | sort -V | head -1)" != "2.1.154" ]; then
    warn "Claude Code $ver detected; saved workflows need >= 2.1.154 (everything else still works)"
  elif [ -n "$ver" ]; then
    ok "Claude Code $ver (>= 2.1.154)"
  fi
else
  warn "'claude' not on PATH — could not verify Claude Code >= 2.1.154"
fi

# 1. python3 — every hook runs through it. When it is ABSENT, the compile/JSON/mem
# checks below cannot run; they are skipped with a warn rather than emitting a
# cascade of misleading 'does not compile' / 'not valid JSON' FAILs (CONF43).
if command -v python3 >/dev/null 2>&1; then
  HAVE_PY=1
  ok "python3 on PATH ($(python3 --version 2>&1))"
else
  HAVE_PY=0
  bad "python3 not on PATH — every hook is inert"
fi

# 2. Every component the repo ships is installed (and hooks compile).
for f in "$SRC"/hooks/*.py; do
  t="$DST/hooks/$(basename "$f")"
  if [ ! -f "$t" ]; then
    bad "hook missing: $t (re-run ./install.sh)"
  elif [ "$HAVE_PY" -eq 0 ]; then
    warn "hook present but compile-unchecked (no python3): $(basename "$f")"
  elif ! python3 -m py_compile "$t" 2>/dev/null; then
    bad "hook does not compile: $t"
  elif ! crlf_same "$f" "$t"; then
    warn "hook differs from this repo checkout: $t (older kit version? re-run ./install.sh)"
  else
    ok "hook: $(basename "$f")"
  fi
done
for f in "$SRC"/agents/*.md; do
  t="$DST/agents/$(basename "$f")"
  if [ ! -f "$t" ]; then
    bad "agent missing: $t"
  elif ! agent_same "$f" "$t"; then
    warn "agent differs from this repo checkout: $t (re-run ./install.sh)"
  else
    ok "agent: $(basename "$f")"
  fi
done
for f in "$SRC"/workflows/*.js; do
  t="$DST/workflows/$(basename "$f")"
  if [ ! -f "$t" ]; then
    bad "workflow missing: $t"
  elif ! crlf_same "$f" "$t"; then
    warn "workflow differs from this repo checkout: $t (re-run ./install.sh)"
  else
    ok "workflow: /$(basename "$f" .js)"
  fi
done
for d in "$SRC"/skills/*/; do
  name="$(basename "$d")"; complete=1; drifted=0
  while IFS= read -r -d '' f; do
    rel="${f#"${d%/}"/}"
    if [ ! -f "$DST/skills/$name/$rel" ]; then
      bad "skill file missing: $DST/skills/$name/$rel"; complete=0
    elif ! crlf_same "$f" "$DST/skills/$name/$rel"; then
      warn "skill file differs from this repo checkout: $DST/skills/$name/$rel (older kit version? re-run ./install.sh)"; drifted=1
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
elif [ "$HAVE_PY" -eq 0 ]; then
  warn "mem CLI present but unchecked (no python3): $MEM"
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
  crlf_same "$SRC/cli/mem.py" "$MEM" || warn "mem CLI differs from this repo checkout: $MEM (re-run ./install.sh)"
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
elif [ "$HAVE_PY" -eq 0 ]; then
  warn "settings.json present but JSON-unchecked (no python3): $SETTINGS"
elif ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SETTINGS" 2>/dev/null; then
  bad "settings.json is not valid JSON — Claude Code will ignore it"
else
  ok "settings.json parses"
  # Event-level wiring: a bare substring test of the filename cannot tell a hook
  # wired to the WRONG event, nor a partial merge that dropped one block of a
  # multi-event hook (e.g. the loop alarm's PostToolUseFailure) from a correct one.
  # Compare each hook's presence PER EVENT against the shipped snippet's own event
  # map (matcher-agnostic, so a widened Bash|PowerShell matcher is accepted), and
  # flag the wrong-interpreter mistake: the Windows snippet's bare `python` commands
  # merged on a POSIX box are hooks that never fire (mirror of doctor.ps1's guard).
  wiring="$(python3 - "$SRC/settings/settings-snippet.json" "$SETTINGS" <<'PY'
import json, sys

def event_map(obj):
    m = {}
    for event, groups in (obj.get("hooks") or {}).items():
        for group in groups or []:
            for h in group.get("hooks") or []:
                name = (h.get("command") or "").rstrip().split("/")[-1]
                if name:
                    m.setdefault(event, set()).add(name)
    return m

expected = event_map(json.load(open(sys.argv[1])))
settings = json.load(open(sys.argv[2]))
actual = event_map(settings)
fail = 0
for event in sorted(expected):
    for name in sorted(expected[event]):
        if name in actual.get(event, set()):
            print(f"ok\twired: {name} [{event}]")
        else:
            print(f"bad\tNOT wired under {event} in settings.json: {name} (merge the snippet from install.sh)")
            fail = 1
for groups in (settings.get("hooks") or {}).values():
    for group in groups or []:
        for h in group.get("hooks") or []:
            if ((h.get("command") or "").split()[:1] == ["python"]):
                print("warn\tsettings.json invokes bare 'python' (the WINDOWS snippet) - most POSIX boxes have only 'python3', so those hooks are inert; merge settings-snippet.json instead")
                raise SystemExit(fail)
raise SystemExit(fail)
PY
)"
  wrc=$?
  while IFS=$'\t' read -r kind msg; do
    case "$kind" in
      ok)   ok "$msg" ;;
      bad)  bad "$msg" ;;
      warn) warn "$msg" ;;
    esac
  done <<< "$wiring"
  [ "$wrc" -eq 0 ] || fail=1
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
