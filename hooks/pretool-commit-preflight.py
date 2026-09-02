#!/usr/bin/env python3
"""PreToolUse commit/push preflight (hardmode).

Doctrine says: run the project's canonical check before declaring anything done. The
moment that matters most is `git commit` / `git push` — a commit made on edits that
no check has seen since is exactly how a red main branch starts. The loop-alarm hook
already tracks, per session and per subagent, how many successful modifications
happened (`edits`) and at which edit count a recognised check last PASSED
(`green_at`). This hook reads that state when a commit or push is about to run and,
if edits happened after the last green check (or no check ever passed), injects a
one-line PREFLIGHT nudge as additionalContext (PreToolUse honours it on 2.1.258).

Non-blocking by default — the human stays the authority, and a docs-only commit is
a legitimate reason to skip a check. HARDMODE_PREFLIGHT=block turns it into a hard
deny (exit 2); HARDMODE_PREFLIGHT=off disables it. Fails open.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob

from _hardmode import (blank_quotes, ledger, normalize_cmd, read_json,  # noqa: E402
                       reconfigure_utf8, scope_slug, session_slug, state_dir)

_COMMIT_OR_PUSH = re.compile(
    r"(?:^|[;&|\n]\s*)(?:[A-Za-z_]\w*=\S*\s+)*(?:sudo\s+)?git\s+(?:(?:-[cC]\s+\S+|--[\w-]+(?:=\S+)?)\s+)*(commit|push)(?![\w-])")


def pending_edits(data):
    """Edits since the last passing check, aggregated over the main thread AND every
    subagent of the session when the commit is issued on the main thread (delegated
    edits are exactly the ones nobody re-checked). Inside a subagent, its own scope."""
    d = state_dir()
    if data.get("agent_id"):
        files = [os.path.join(d, f"loop-alarm-{scope_slug(data)}.json")]
    else:
        files = glob.glob(os.path.join(d, f"loop-alarm-{session_slug(data)}*.json"))
    since, ever_green = 0, False
    for f in files:
        st = read_json(f, {})
        edits = int(st.get("edits", 0) or 0)
        green_at = st.get("green_at")
        green_at = int(green_at) if green_at is not None else -1
        if green_at >= 0:
            ever_green = True
            since += max(0, edits - green_at)
        else:
            since += edits
    return since, ever_green


def main():
    reconfigure_utf8(sys.stdin, sys.stdout, sys.stderr)
    mode = os.environ.get("HARDMODE_PREFLIGHT", "nudge").lower()
    if mode == "off":
        return 0
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(cmd, str) or "git" not in cmd:
        return 0
    m = _COMMIT_OR_PUSH.search(blank_quotes(normalize_cmd(cmd)))
    if not m:
        return 0
    verb = m.group(1)
    since, ever_green = pending_edits(data)
    if since == 0:
        return 0
    what = (f"{since} modification(s) landed and no recognised check has passed in this session"
            if not ever_green else f"{since} modification(s) landed after the last passing check")
    note = (f"PREFLIGHT (automated): you are about to `git {verb}` but {what}. Run the "
            "project's canonical check (pytest / npm test / make check / verify.sh ...) and "
            "read its result first — or state in the commit message why no check applies "
            "(docs-only, generated files).")
    ledger(data, "commit-preflight", "block" if mode == "block" else "nudge", f"{verb}:{since}")
    if mode == "block":
        print(note + " (HARDMODE_PREFLIGHT=block: the command is denied until a check passes.)",
              file=sys.stderr)
        return 2
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "additionalContext": note}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
