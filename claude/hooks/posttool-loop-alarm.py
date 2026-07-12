#!/usr/bin/env python3
"""PostToolUse / PostToolUseFailure loop-alarm hook (fable-protocol).

Deterministic backstop for the grinding failure mode: the doctrine's "two failed
fixes -> oracle" rule is advisory, and the benchmark showed advisory rules get
skipped under momentum. This hook counts, per session, how many times the SAME
Bash command has failed since the last successful file modification. On the 3rd
identical failure (configurable via FABLE_LOOP_THRESHOLD; use 2 on smaller driver
models) it injects a one-time nudge (exit 2 -> stderr shown to the model;
PostToolUse cannot block, the command already ran).

EVENT MODEL (verified against Claude Code 2.1.207 — DO NOT REGRESS)
    A failing Bash command fires PostToolUseFailure, NOT PostToolUse, and its
    payload carries NO exit-code/is_error field — failure is signalled by the
    event itself (plus an `error` string). A succeeding command fires PostToolUse
    with a `tool_response` and no exit code. The two events are mutually exclusive.
    So this hook MUST be wired to BOTH events: PostToolUseFailure is the only place
    it can see a failure, PostToolUse is where it observes the successes that reset
    the grind counter. The pre-2.1 shape (exit codes inside a PostToolUse
    tool_response) is still honoured via failed() so the hook works on both.

Key design point: a SUCCESSFUL file modification (Edit/Write/NotebookEdit, or a
succeeding file-writing Bash command) clears all counts — re-running a check after
a change is legitimate iteration. A FAILING write-command does NOT reset (a write
that keeps failing is itself a grind — the CONF0 bug this replaces let such a
command clear its own count on every run). Only "same command, still failing,
nothing successfully changed in between" accumulates.
"""
import json
import os
import re
import sys
import time

THRESHOLD_DEFAULT = 3
MAX_TRACKED = 50
STATE_TTL_DAYS = 7


def threshold():
    """FABLE_LOOP_THRESHOLD overrides the default (clamped 2..10).

    Smaller models grind harder: on a Sonnet/Haiku driver set it to 2 —
    the second identical failure is already the signal (docs/SUCCESSION.md).
    """
    try:
        v = int(os.environ.get("FABLE_LOOP_THRESHOLD", ""))
        if 2 <= v <= 10:
            return v
    except ValueError:
        pass
    return THRESHOLD_DEFAULT

MODIFYING_TOOLS = {"Edit", "Write", "NotebookEdit"}
# Same conservative "this Bash command plausibly writes files" heuristic as the
# claim-audit gate. Kept byte-identical to stop-claim-audit.BASH_WRITE and enforced
# by tests/test_loop_alarm.py::test_bash_write_in_sync_with_claim_audit.
BASH_WRITE = re.compile(
    r"(?<![0-9&])>>?\s*(?!&|/dev/(?:null|stdout|stderr)\b)\S"
    r"|(?:^|[|&;]\s*)(?:sed\s+(?:-\S+\s+)*-i|tee\s|patch\s|truncate\s"
    r"|(?:git\s+(?:apply|mv|rm|checkout|restore|stash))|mv\s|cp\s|rm\s)"
)

NUDGE = (
    "LOOP ALARM (automated, fires once per command): this exact command has now failed "
    "{n} times with no successful change in between. Running it again will not produce "
    "new information. Stop grinding: (1) write the dead hypotheses down, one line each; "
    "(2) run the cheapest DIFFERENT experiment that discriminates between the survivors — "
    "or hand ALL evidence to the `oracle` agent now. A third identical attempt is the "
    "documented failure mode this alarm exists to catch."
)


def state_dir():
    d = os.environ.get("FABLE_STATE_DIR") or os.path.join(
        os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude"),
        "tmp", "fable-protocol")
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


def load_state(path):
    try:
        with open(path) as f:
            s = json.load(f)
        if isinstance(s, dict):
            return {"counts": dict(s.get("counts", {})), "nudged": list(s.get("nudged", []))}
    except (OSError, ValueError):
        pass
    return {"counts": {}, "nudged": []}


def save_state(path, state):
    if len(state["counts"]) > MAX_TRACKED:
        # Drop oldest-inserted keys; dict preserves insertion order.
        for k in list(state["counts"])[: len(state["counts"]) - MAX_TRACKED]:
            del state["counts"][k]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def failed(tool_response):
    """Legacy-CLI failure evidence: an explicit non-zero exit code / is_error flag
    inside a PostToolUse tool_response. Claude Code 2.1.x omits these (it routes
    failures to PostToolUseFailure instead), so this only matters on older builds."""
    if not isinstance(tool_response, dict):
        return False
    for key in ("exit_code", "exitCode", "returnCode", "code"):
        v = tool_response.get(key)
        if isinstance(v, int):
            return v != 0
    for key in ("is_error", "isError"):
        if tool_response.get(key) is True:
            return True
    return False


def main():
    data = json.load(sys.stdin)
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id", "unknown")))[:80]
    d = state_dir()
    prune_stale(d)
    path = os.path.join(d, f"loop-alarm-{session}.json")
    state = load_state(path)

    event = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    cmd = re.sub(r"\s+", " ", cmd).strip() if isinstance(cmd, str) else ""

    # Failure signal: the dedicated PostToolUseFailure event, or (legacy CLIs) an
    # explicit non-zero exit inside a PostToolUse tool_response.
    is_failure = event == "PostToolUseFailure" or failed(data.get("tool_response"))

    if not is_failure:
        # A SUCCESSFUL modification (or succeeding write-command) means iteration
        # moved forward — retrying checks is legitimate again, so clear everything.
        if tool in MODIFYING_TOOLS or (tool == "Bash" and cmd and BASH_WRITE.search(cmd)):
            state["counts"] = {}
            save_state(path, state)
            return 0
        # A non-write Bash command that succeeded clears only its own count.
        if tool == "Bash" and cmd:
            state["counts"].pop(cmd, None)
            save_state(path, state)
        return 0

    # From here: this is a failure. Only Bash commands are tracked for grinding.
    if tool != "Bash" or not cmd:
        return 0

    n = state["counts"].get(cmd, 0) + 1
    state["counts"][cmd] = n
    if n >= threshold() and cmd not in state["nudged"]:
        state["nudged"].append(cmd)
        save_state(path, state)
        print(NUDGE.format(n=n), file=sys.stderr)
        return 2
    save_state(path, state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break a session over a hook bug — fail open
