#!/usr/bin/env python3
"""PreCompact hook (fable-protocol): save the original request verbatim.

The doctrine's #1 compaction rule is "preserve the original task statement
verbatim" — but that is an instruction to a summarizer, and instructions get
lossy. This hook makes it deterministic: before every compaction it extracts
the FIRST user message from the transcript and writes it to a per-session
state file. The SessionStart(compact) recovery hook injects it back verbatim,
alongside the live git state.

Always exits 0 — PreCompact must never block a compaction the session needs.
"""
import json
import os
import re
import sys

MAX_CHARS = 4000
SYSTEM_TAG = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def state_dir():
    d = os.environ.get("FABLE_STATE_DIR") or os.path.join(
        os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"),
        "tmp", "fable-protocol")
    os.makedirs(d, exist_ok=True)
    return d


def entry_text(entry):
    if entry.get("type") != "user" or entry.get("isMeta"):
        return ""
    content = entry.get("message", {}).get("content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        return ""
    # Harness-injected reminders are not part of the user's request.
    return SYSTEM_TAG.sub("", text).strip()


def first_user_message(transcript_path):
    # Transcripts are UTF-8; the OS-locale default (cp1252 on Windows Python <=3.14)
    # would crash on multi-byte content and lose the save entirely (CONF-UTF8).
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            text = entry_text(entry)
            if text:
                return text
    return ""


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = json.load(sys.stdin)
    text = first_user_message(data["transcript_path"])
    if not text:
        return 0
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[... truncated — full text in transcript]"
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id", "unknown")))[:80]
    path = os.path.join(state_dir(), f"original-task-{session}.txt")
    tmp = path + ".tmp"
    # utf-8 explicitly: the user's request may contain characters the OS-locale
    # default (cp1252) cannot encode — a crash here silently loses the save.
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never block a compaction over a hook bug
