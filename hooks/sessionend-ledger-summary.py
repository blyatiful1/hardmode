#!/usr/bin/env python3
"""SessionEnd hook (hardmode): roll the session's firing ledger into one summary line.

Every hardmode hook appends its decisions to ledger-<session>.jsonl. At SessionEnd
this hook counts them and appends ONE line to sessions.jsonl in the state dir:

  {"session": ..., "reason": ..., "ended": <unix ts>, "events": N,
   "by_hook": {"claim-audit:block": 1, "destructive-guard:block": 2, ...}, "cwd": ...}

That file is the denominator (sessions) without which firing counts mean nothing —
tools/stats.py and /hardmode:stats read it, and the SessionStart floor check uses
the previous line to tell the next session what fired. Kept to the newest 500 lines.

Constraints (verified 2.1.258): SessionEnd hooks race a 5s process-exit timer and
their stdout is discarded, so this is pure file I/O, prints nothing, no subprocess,
and is wired with an explicit short timeout. Always exits 0.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import iter_jsonl, locked, reconfigure_utf8, session_slug, state_dir  # noqa: E402

MAX_SESSIONS = 500


def summarize(ledger_path):
    by_hook, n = {}, 0
    for rec in iter_jsonl(ledger_path):
        n += 1
        key = f"{rec.get('hook', '?')}:{rec.get('outcome', '?')}"
        by_hook[key] = by_hook.get(key, 0) + 1
    return n, by_hook


def main():
    reconfigure_utf8(sys.stdin)
    data = json.load(sys.stdin)
    d = state_dir()
    session = session_slug(data)
    ledger_path = os.path.join(d, f"ledger-{session}.jsonl")
    n, by_hook = summarize(ledger_path) if os.path.isfile(ledger_path) else (0, {})
    line = {"session": session, "reason": data.get("reason") or "", "ended": int(time.time()),
            "events": n, "by_hook": by_hook, "cwd": str(data.get("cwd") or "")[:200]}
    path = os.path.join(d, "sessions.jsonl")
    with locked(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except OSError:
            lines = []
        lines.append(json.dumps(line, ensure_ascii=False))
        lines = lines[-MAX_SESSIONS:]
        tmp = f"{path}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
