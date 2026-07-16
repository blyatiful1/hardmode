#!/usr/bin/env python3
"""SessionEnd memory-journal hook (fable-protocol, L3).

WHY THIS EXISTS
    Two jobs, both deterministic side effects at session teardown:

    1. BREADCRUMB — append exactly one NDJSON line to `$BASE/memory/journal.ndjson`
       recording that a session happened and roughly what it touched (ISO ts, cwd,
       git root + branch + dirty-file count, end reason). SessionEnd carries no
       native session metadata beyond `reason`, so the hook computes its own
       breadcrumbs via a hard-bounded `git` subprocess. This gives a trace even
       for sessions that banked no memory — the raw material `/memory-review`
       mines for capture candidates.

    2. FRESHNESS — after writing the line, run an INCREMENTAL `mem.py index`
       (mtime-walk, only changed files) so memory written this session is searchable
       in the next one. This is the only place the index is refreshed on the hot path.

    The journal line is written BEFORE the reindex, and the breadcrumb's git
    subprocesses carry BOTH a per-call timeout AND a small TOTAL wall-clock budget
    (GIT_TOTAL_BUDGET), so three sequential git calls can never approach the 10s
    SessionEnd budget: the line is durable within a few seconds even when git hangs,
    long before the harness kill. (The earlier 3×5s per-call bound could reach 15s of
    git before the append — past the 10s kill — silently losing the breadcrumb on
    exactly the big/slow-repo sessions /memory-review most wants to mine.)

FAIL-OPEN GUARANTEE
    SessionEnd cannot block teardown and must never raise. Any failure — malformed
    stdin, no git, a missing/broken mem.py, an I/O error — ends in `sys.exit(0)`.
    The journal write and the reindex are independent: a reindex failure never
    costs the breadcrumb (already flushed), and a journal-write failure still lets
    the reindex run.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

JOURNAL_NAME = "journal.ndjson"
ROTATED_NAME = "journal.1.ndjson"
ROTATE_BYTES = 5 * 1024 * 1024      # 5 MB
GIT_TIMEOUT = 2                     # per-git-call hard bound (s)
GIT_TOTAL_BUDGET = 4               # total wall-clock across ALL git calls (s) — must
#                                    stay well under the 10s SessionEnd budget so the
#                                    breadcrumb is written before any harness kill.
REINDEX_TIMEOUT = 8                 # hard bound on the incremental reindex


def base_dir():
    return os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude")


def memory_dir(base):
    return os.path.join(base, "memory")


def journal_path(base):
    return os.path.join(memory_dir(base), JOURNAL_NAME)


def _git(args, cwd, timeout):
    """Run a git command with a hard timeout. Returns stdout on success, else None.
    A non-positive timeout means the total git budget is spent — skip the call."""
    if timeout <= 0:
        return None
    try:
        p = subprocess.run(
            ["git"] + args, cwd=cwd or None,
            capture_output=True, text=True, timeout=timeout,
        )
        if p.returncode != 0:
            return None
        return p.stdout
    except Exception:
        return None


def git_breadcrumbs(cwd):
    """Return {git_root, branch, dirty_count} — each key omitted if git can't answer.
    A deterministic trace even when git is absent or cwd is not a repo.

    Every call is bounded by BOTH GIT_TIMEOUT (per call) and a shared GIT_TOTAL_BUDGET
    deadline, so however slow/hanging git is, all three calls together finish within a
    few seconds — the caller then appends the breadcrumb well before the SessionEnd
    kill. A hang just yields a git-less (but still durable) line."""
    out = {}
    deadline = time.monotonic() + GIT_TOTAL_BUDGET

    def budget():
        return min(GIT_TIMEOUT, deadline - time.monotonic())

    root = _git(["rev-parse", "--show-toplevel"], cwd, budget())
    if root is not None and root.strip():
        out["git_root"] = root.strip()
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd, budget())
    if branch is not None and branch.strip():
        out["branch"] = branch.strip()
    status = _git(["status", "--porcelain"], cwd, budget())
    if status is not None:
        out["dirty_count"] = len([ln for ln in status.splitlines() if ln.strip()])
    return out


def build_line(data):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cwd": data.get("cwd", ""),
        "reason": data.get("reason", ""),
    }
    entry.update(git_breadcrumbs(data.get("cwd")))
    return json.dumps(entry, ensure_ascii=False)


def rotate_if_big(path):
    """Rename the journal to journal.1.ndjson once it crosses 5 MB, so appends land
    in a fresh file. Best-effort — a rotation failure never blocks the append."""
    try:
        if os.path.exists(path) and os.path.getsize(path) >= ROTATE_BYTES:
            os.replace(path, os.path.join(os.path.dirname(path), ROTATED_NAME))
    except OSError:
        pass


def write_journal(base, data):
    """Append one NDJSON line. Returns True on success (breadcrumb durable)."""
    path = journal_path(base)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return False
    rotate_if_big(path)
    line = build_line(data)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except OSError:
        return False


def reindex(base):
    """Incremental `mem.py index` side effect — best-effort, hard-timeout-bounded.
    Pins CLAUDE_DIR=base so the subprocess indexes the SAME corpus this hook resolved,
    even if the caller passed a base that differs from the ambient CLAUDE_DIR."""
    mem_py = os.path.join(base, "cli", "mem.py")
    if not os.path.exists(mem_py):
        return
    try:
        subprocess.run(
            [sys.executable, mem_py, "index"],
            env=dict(os.environ, CLAUDE_DIR=base),
            capture_output=True, text=True, timeout=REINDEX_TIMEOUT,
        )
    except Exception:
        pass  # a stale index is recoverable next session; never break teardown


def main():
    # The payload is UTF-8 regardless of OS locale; on Windows Python <=3.14 the cp1252
    # default would UnicodeError on a multi-byte cwd/reason and drop the stdin data,
    # writing a blank breadcrumb instead of the real one.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    base = base_dir()
    write_journal(base, data)   # breadcrumb FIRST — durable even if reindex is killed
    reindex(base)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open — never break a session over a hook bug
