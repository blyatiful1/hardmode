#!/usr/bin/env python3
"""PostToolUse test-weakening alarm (fable-protocol).

The reward-hacking variant of the false-green failure mode: greening a failing
suite by skipping/disabling the test instead of fixing the code. The doctrine
forbids it and the Stop-hook audit asks about it after the fact — but both are
downstream of the edit. This hook watches the edit itself: when an Edit/Write/
MultiEdit adds a skip/disable marker to a test file, it injects a one-time
nudge (exit 2 -> stderr shown to the model; PostToolUse cannot block, the edit
already landed).

Only ADDED markers count: an edit that merely moves existing skips around, or
touches a file that already had them, stays silent (occurrences in the new
text must exceed occurrences in the old text). Legitimate skips survive — the
nudge demands an explicit justification in the final message, not a revert.

Fires once per file per session. Fails open on any error.
"""
import json
import os
import re
import sys
import time

STATE_TTL_DAYS = 7

# Same test-path heuristic as the claim-audit gate (kept in sync by tests).
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)"
    r"|(^|/)test_[^/]+$"
    r"|_test\.[A-Za-z0-9]+$"
    r"|\.(test|spec)\.[A-Za-z0-9]+$",
    re.IGNORECASE,
)

# Skip/disable markers across the mainstream ecosystems. Conservative: each
# pattern is something a test author writes to STOP a test from running, not
# something that appears in ordinary test bodies.
SKIP_MARKERS = re.compile(
    r"@pytest\.mark\.(?:skip|skipif|xfail)"      # pytest decorators
    r"|\bpytest\.(?:skip|xfail)\s*\("            # pytest imperative
    r"|@unittest\.(?:skip|skipIf|skipUnless|expectedFailure)"  # unittest
    r"|\b(?:it|test|describe)\.skip\s*[(.]"      # jest/mocha/vitest .skip
    r"|\bx(?:it|test|describe)\s*\("             # jasmine/jest x-prefix
    r"|\bt\.Skip[f]?\s*\("                       # Go testing
    r"|#\[ignore[\](]"                           # Rust #[ignore] / #[ignore(...)]
    r"|@Disabled\b|@Ignore\b",                   # JUnit 5 / JUnit 4
)

NUDGE = (
    "TEST-WEAKENING ALARM (automated, fires once per file): this edit ADDS a "
    "skip/disable marker to a test file ({path}). Greening a failing suite by "
    "skipping the test is not a fix — the doctrine forbids it. Either (a) revert "
    "the skip and fix the underlying failure, or (b) if the skip is genuinely "
    "warranted (platform guard, known-flaky quarantine the user approved), keep it "
    "AND say so explicitly in your final message with the justification."
)


def state_dir():
    d = os.environ.get("FABLE_STATE_DIR") or os.path.expanduser("~/.claude/tmp/fable-protocol")
    os.makedirs(d, exist_ok=True)
    return d


def prune_stale(d):
    cutoff = time.time() - STATE_TTL_DAYS * 86400
    for name in os.listdir(d):
        p = os.path.join(d, name)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.unlink(p)
        except OSError:
            pass


def marker_count(text):
    return len(SKIP_MARKERS.findall(text)) if isinstance(text, str) else 0


def added_markers(tool, tool_input):
    """True iff this tool call introduces skip markers that were not there before."""
    if tool == "Edit":
        return marker_count(tool_input.get("new_string")) > marker_count(tool_input.get("old_string"))
    if tool == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return False
        return any(
            isinstance(e, dict)
            and marker_count(e.get("new_string")) > marker_count(e.get("old_string"))
            for e in edits
        )
    if tool == "Write":
        # No old content in the payload; compare against the file on disk is
        # impossible post-write. A brand-new test file written WITH a skip in it
        # is exactly as suspicious as an added one — count any marker.
        return marker_count(tool_input.get("content")) > 0
    return False


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write", "MultiEdit"):
        return 0
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    path = tool_input.get("file_path", "")
    if not isinstance(path, str) or not TEST_PATH.search(path):
        return 0
    if not added_markers(tool, tool_input):
        return 0

    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id", "unknown")))[:80]
    d = state_dir()
    prune_stale(d)
    state_path = os.path.join(d, f"weakening-alarm-{session}.json")
    try:
        with open(state_path) as f:
            nudged = json.load(f)
        if not isinstance(nudged, list):
            nudged = []
    except (OSError, ValueError):
        nudged = []
    if path in nudged:
        return 0
    nudged.append(path)
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(nudged, f)
    os.replace(tmp, state_path)
    print(NUDGE.format(path=path), file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break a session over a hook bug — fail open
