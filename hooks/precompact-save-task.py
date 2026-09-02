#!/usr/bin/env python3
"""PreCompact hook (hardmode): save what a summary most reliably mangles.

The doctrine's compaction rule is "preserve the original task statement verbatim,
the full list of modified files, the canonical check commands, and the current plan
step" — an instruction to a summarizer, and instructions get lossy. This hook makes
the load-bearing parts deterministic. Before every compaction it writes, per session:

  original-task-<s>.txt   the FIRST genuine user message, verbatim (4000-char cap)
  compact-turns-<s>.txt   the LATEST later user turns (scope changes, corrections)
  compact-snapshot-<s>.txt the git state AT compaction time: branch, HEAD, status,
                          diff --stat, stash count — so the recovery hook can show
                          what was in flight and warn if HEAD moved

and prints the preservation instruction to stdout — on this build a PreCompact
hook's stdout becomes the summarizer's custom instructions, so the summary is TOLD
what it may not paraphrase. The SessionStart(compact) hook injects the files back.

Always exits 0 — PreCompact must never block a compaction the session needs.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import iter_jsonl, ledger, reconfigure_utf8, session_slug, state_dir  # noqa: E402

MAX_CHARS = 4000
MAX_LATER_TURNS = 5
MAX_LATER_CHARS = 600
GIT_TIMEOUT = 2
SYSTEM_TAG = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)

INSTRUCTIONS = (
    "hardmode compaction rule: preserve VERBATIM, never paraphrased — (1) the original "
    "task statement and every later user instruction that changed its scope; (2) the "
    "complete list of files modified this session; (3) the canonical build/test "
    "command(s) and the result of their last run; (4) the current plan step and what "
    "remains undone. Anything unverified stays labelled unverified in the summary."
)


def entry_text(entry):
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return ""
    content = entry.get("message", {}).get("content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    else:
        return ""
    return SYSTEM_TAG.sub("", text).strip()


def user_turns(transcript_path):
    turns = []
    for entry in iter_jsonl(transcript_path):
        text = entry_text(entry)
        if text:
            turns.append(text)
    return turns


def write_atomic(path, text):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def git(args, cwd):
    try:
        p = subprocess.run(["git", *args], cwd=cwd or None, capture_output=True,
                           text=True, timeout=GIT_TIMEOUT)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def git_snapshot(cwd, trigger):
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch is None:
        return None
    head = git(["rev-parse", "--short", "HEAD"], cwd) or ""
    status = git(["status", "--short"], cwd) or ""
    stat = git(["diff", "--stat", "HEAD"], cwd) or ""
    stash = git(["stash", "list"], cwd) or ""
    lines = [f"trigger: {trigger}", f"branch: {branch.strip()}", f"HEAD: {head.strip()}",
             "status:"]
    lines += status.splitlines()[:30] or ["(working tree clean)"]
    if stat.strip():
        lines += ["diff --stat:"] + stat.splitlines()[-8:]
    lines.append(f"stash entries: {len([ln for ln in stash.splitlines() if ln.strip()])}")
    return "\n".join(lines) + "\n"


def main():
    reconfigure_utf8(sys.stdin, sys.stdout)
    data = json.load(sys.stdin)
    print(INSTRUCTIONS)          # summarizer instructions — flushed before any work
    sys.stdout.flush()
    session = session_slug(data)
    d = state_dir()
    turns = user_turns(data.get("transcript_path", ""))
    task_path = os.path.join(d, f"original-task-{session}.txt")
    turns_path = os.path.join(d, f"compact-turns-{session}.txt")
    if turns:
        # Write-once: after a compaction the transcript starts with the summary, so the
        # first visible user turn is a LATER one — it must never overwrite the original.
        if not os.path.exists(task_path):
            first = turns[0]
            if len(first) > MAX_CHARS:
                first = first[:MAX_CHARS] + "\n[... truncated — full text in transcript]"
            write_atomic(task_path, first)
            later = turns[1:]
        else:
            later = turns          # everything visible now came after the original
        try:
            os.unlink(turns_path)  # never re-inject a stale list from an earlier compaction
        except OSError:
            pass
        if later:
            kept = later[-MAX_LATER_TURNS:]
            omitted = len(later) - len(kept)
            parts = []
            if omitted:
                parts.append(f"[... {omitted} intermediate user turn(s) omitted ...]")
            for i, t in enumerate(kept, start=len(later) - len(kept) + 2):
                body = t if len(t) <= MAX_LATER_CHARS else t[:MAX_LATER_CHARS] + " [...]"
                parts.append(f"--- user turn {i}/{len(turns)} ---\n{body}")
            write_atomic(turns_path, "\n".join(parts))
    snap = git_snapshot(data.get("cwd"), data.get("trigger") or "unknown")
    if snap:
        write_atomic(os.path.join(d, f"compact-snapshot-{session}.txt"), snap)
    ledger(data, "precompact-save", "saved", f"turns={len(turns)} snapshot={'y' if snap else 'n'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never block a compaction over a hook bug
