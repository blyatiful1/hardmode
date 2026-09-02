#!/usr/bin/env python3
"""SessionStart(compact) recovery hook (hardmode).

Runs immediately after a compaction and injects (stdout -> context), in order:
  1. the recovery protocol (what to re-read before acting),
  2. the ORIGINAL user request verbatim and the latest later user turns, saved by
     the PreCompact hook — the things a summary most reliably mangles,
  3. the git state AS IT WAS at compaction time (branch, HEAD, modified files),
  4. the ACTUAL current git state, with a warning if HEAD moved in between.

Deterministic data beats a summary's recollection. Fails open: on any error it
still prints the protocol text. Everything that must survive is flushed before
the first git call, whose budget is bounded (3s per call).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import ledger, reconfigure_utf8, session_slug, state_dir  # noqa: E402

PROTOCOL = (
    "CONTEXT JUST COMPACTED — recovery protocol: (1) the ORIGINAL request and the later "
    "user instructions are injected verbatim below (when available) — re-read them and "
    "your task list; (2) the git state at compaction time AND the actual current state "
    "are injected below — trust them over your summary of which files you modified; "
    "(3) re-read the current plan step before acting; (4) anything the summary calls "
    "done that you cannot see evidence for is unverified. Do not trust the summary of "
    "the summary."
)
GIT_TIMEOUT = 3
MAX_CHARS = 12000


def run(cmd, cwd):
    try:
        p = subprocess.run(cmd, cwd=cwd or None, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)
        return p.returncode == 0, p.stdout
    except Exception:
        return False, ""


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def main():
    reconfigure_utf8(sys.stdin, sys.stdout)
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    print(PROTOCOL)
    session = session_slug(data)
    d = state_dir(create=False)
    out = []
    task = read(os.path.join(d, f"original-task-{session}.txt"))
    if task:
        out.append("\n--- original request (verbatim, saved pre-compaction) ---\n" + task)
    turns = read(os.path.join(d, f"compact-turns-{session}.txt"))
    if turns:
        out.append("\n--- later user instructions (verbatim, newest last) ---\n" + turns)
    snap = read(os.path.join(d, f"compact-snapshot-{session}.txt"))
    saved_head = ""
    if snap:
        for ln in snap.splitlines():
            if ln.startswith("HEAD: "):
                saved_head = ln[6:].strip()
        out.append("\n--- git state AT compaction time (deterministic) ---\n" + snap)
    text = "\n".join(out)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[... recovery text truncated ...]"
    if text:
        print(text)
    sys.stdout.flush()   # everything above must survive a git hang below

    cwd = data.get("cwd")
    ok, status = run(["git", "status", "--short"], cwd)
    if ok:
        print("\n--- actual git state NOW (post-compaction, deterministic) ---")
        print("\n".join(status.splitlines()[:30]) if status.strip() else "(working tree clean)")
        _, stat = run(["git", "diff", "--stat", "HEAD"], cwd)
        if stat.strip():
            print("\n".join(stat.splitlines()[-8:]))
        ok_h, head = run(["git", "rev-parse", "--short", "HEAD"], cwd)
        if ok_h and saved_head and head.strip() and head.strip() != saved_head:
            print(f"WARNING: HEAD moved since the pre-compaction snapshot ({saved_head} -> "
                  f"{head.strip()}) — commits or resets happened; re-derive what is committed.")
    ledger(data, "compact-recovery", "injected",
           f"task={'y' if task else 'n'} turns={'y' if turns else 'n'} snapshot={'y' if snap else 'n'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print(PROTOCOL)
        sys.exit(0)  # fail open — at minimum the protocol text gets injected
