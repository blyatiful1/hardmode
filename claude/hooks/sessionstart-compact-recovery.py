#!/usr/bin/env python3
"""SessionStart(compact) recovery hook (fable-protocol).

Runs immediately after a compaction and injects (stdout -> context), in order:
  1. the recovery protocol (what to re-read before acting),
  2. the ORIGINAL user request verbatim, saved by the PreCompact hook —
     the one thing a summary most reliably mangles,
  3. the ACTUAL current git state — deterministic data beats a summary's
     recollection of which files were modified.

Replaces the earlier inline-shell version of this hook (v1.2) so the original
request can be recovered from the per-session state file. Fails open: on any
error it still prints the protocol text.
"""
import json
import os
import re
import subprocess
import sys

PROTOCOL = (
    "CONTEXT JUST COMPACTED — recovery protocol: (1) the ORIGINAL request is injected "
    "verbatim below (when available) — re-read it and your task list; (2) the ACTUAL "
    "current git state is injected below — trust it over your summary of which files "
    "you modified; (3) re-read the current plan step before acting. Do not trust the "
    "summary of the summary."
)


def state_dir():
    return os.environ.get("FABLE_STATE_DIR") or os.path.join(
        os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"),
        "tmp", "fable-protocol")


# Total git budget must fit inside the hook's 10s timeout with headroom: two calls
# at 3s each = 6s worst case, so a hung repo can never starve the flush below (CONF7).
GIT_TIMEOUT = 3


def run(cmd, cwd):
    """Returns (ok, stdout) — ok distinguishes 'clean output' from 'not a repo'."""
    try:
        p = subprocess.run(cmd, cwd=cwd or None, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)
        return p.returncode == 0, p.stdout
    except Exception:
        return False, ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    print(PROTOCOL)

    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id", "unknown")))[:80]
    task_file = os.path.join(state_dir(), f"original-task-{session}.txt")
    try:
        with open(task_file) as f:
            task = f.read().strip()
    except OSError:
        task = ""
    if task:
        print("\n--- original request (verbatim, saved pre-compaction) ---")
        print(task)

    # Flush the two things a git hang must never lose (protocol + original request)
    # BEFORE spending any of the budget on subprocesses. Under a hook, stdout is
    # block-buffered, so a timeout-kill mid-git would otherwise discard everything.
    sys.stdout.flush()

    cwd = data.get("cwd")
    ok, status = run(["git", "status", "--short"], cwd)
    if ok:
        print("\n--- actual git state (post-compaction, deterministic) ---")
        print("\n".join(status.splitlines()[:30]) if status.strip() else "(working tree clean)")
        _, stat = run(["git", "diff", "--stat", "HEAD"], cwd)
        if stat.strip():
            print("\n".join(stat.splitlines()[-8:]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print(PROTOCOL)
        sys.exit(0)  # fail open — at minimum the protocol text gets injected
