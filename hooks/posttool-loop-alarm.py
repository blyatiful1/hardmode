#!/usr/bin/env python3
"""Loop-alarm hook (hardmode) — PostToolUse, PostToolUseFailure and PreToolUse(Edit).

Deterministic backstop for the grinding failure mode: the doctrine's "two failed
fixes -> oracle" rule is advisory, and the benchmark showed advisory rules get
skipped under momentum. This hook counts, per session (and per subagent), how many
times the SAME thing has failed since the last successful change:

  * a shell command (Bash) that keeps failing — counted on PostToolUseFailure;
  * an Edit with the same file_path + old_string sent again and again — counted on
    PreToolUse(Edit), because an `old_string not found` rejection fires NO post-tool
    event at all, and a repeat of an identical edit after a SUCCESSFUL one can only
    be a retry (the old_string is gone) or a flip-flop.

On the Nth identical failure (HARDMODE_LOOP_THRESHOLD, default 3) it injects a
one-time nudge: exit 2 with the reason on stderr. On PostToolUseFailure that is a
nudge after the fact (the command already ran); on PreToolUse(Edit) it DENIES the
identical edit — which would have failed anyway — and tells the model why.

EVENT MODEL (verified against Claude Code 2.1.258 — DO NOT REGRESS)
    A failing tool call fires PostToolUseFailure (payload: error string, is_interrupt),
    NOT PostToolUse; a succeeding one fires PostToolUse. Neither carries an exit code —
    failure is the event itself. The pre-2.1 shape (exit codes inside a PostToolUse
    tool_response) is still honoured via failed(). A user interrupt (Esc) also arrives
    as PostToolUseFailure with is_interrupt=true and is NOT counted as a failure.

Reset rule: a SUCCESSFUL modification (Edit/Write/NotebookEdit, or a succeeding shell
command that mutates SOURCE — sed -i, patch, mv/cp, a git file op) clears all counts:
re-running a check after a real change is legitimate iteration. A bare `>`/`>>`
redirect or `tee` does NOT reset — piping a failing check to a log is the normal
mid-grind move, and treating it as progress let one diagnostic redirect disarm the
alarm. A FAILING command never resets.

The same state file also records, for the commit-preflight hook, how many successful
modifications happened since a recognised check last passed (`edits`, `green_at`).
State is locked around each read-modify-write (parallel tool calls), keyed per
session AND per subagent, and stores only hashes of commands — never their text.
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import (ledger, locked, looks_like_test_run, prune_stale,  # noqa: E402
                       read_json, reconfigure_utf8, scope_slug, state_dir,
                       write_json_atomic)

THRESHOLD_DEFAULT = 3
MAX_TRACKED = 50


def threshold():
    """HARDMODE_LOOP_THRESHOLD overrides the default (clamped 2..10). A smaller or
    grindier driver model can use 2: the second identical failure is the signal."""
    try:
        v = int(os.environ.get("HARDMODE_LOOP_THRESHOLD", ""))
        if 2 <= v <= 10:
            return v
    except ValueError:
        pass
    return THRESHOLD_DEFAULT


MODIFYING_TOOLS = {"Edit", "Write", "NotebookEdit"}
SHELL_TOOLS = {"Bash"}
# A SUCCEEDING shell command clears the grind counter ONLY when it mutates source.
# Deliberately NARROWER than the claim gate's SHELL_WRITE: no bare redirects, no tee.
LOOP_RESET = re.compile(
    r"(?:^|[|&;]\s*)(?:sed\s+(?:-\S+\s+)*-i|patch\s"
    r"|(?:git\s+(?:apply|mv|rm|checkout|restore|stash))|mv\s|cp\s)"
)

NUDGE = (
    "LOOP ALARM (automated, fires once per command): this exact command has now failed "
    "{n} times with no successful change in between. Running it again will not produce "
    "new information. Stop grinding: (1) write the dead hypotheses down, one line each; "
    "(2) run the cheapest DIFFERENT experiment that discriminates between the survivors — "
    "or hand ALL evidence to the `hardmode:oracle` agent now. Another identical attempt is "
    "the documented failure mode this alarm exists to catch."
)
EDIT_NUDGE = (
    "LOOP ALARM (automated): this exact Edit — same file, same old_string — has now been "
    "attempted {n} times. It is denied because an identical retry cannot succeed where the "
    "last one failed: either old_string no longer matches the file (re-read the file and "
    "copy the current text verbatim) or the edit is flip-flopping. Do not resend it "
    "unchanged; if you are truly stuck, hand the evidence to the `hardmode:oracle` agent."
)


def _h(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:24]


def norm_cmd(tool_input):
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    return re.sub(r"\s+", " ", cmd).strip() if isinstance(cmd, str) else ""


def grind_key(tool, tool_input):
    if tool in SHELL_TOOLS:
        cmd = norm_cmd(tool_input)
        return ("sh:" + _h(cmd)) if cmd else None
    if tool == "Edit" and isinstance(tool_input, dict):
        fp = str(tool_input.get("file_path", ""))
        old = str(tool_input.get("old_string", ""))
        return ("ed:" + _h(fp + "\0" + old)) if fp else None
    if tool in MODIFYING_TOOLS and isinstance(tool_input, dict):
        fp = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        return ("wr:" + _h(tool + "\0" + fp)) if fp else None
    return None


def load_state(path):
    s = read_json(path, {})
    return {"counts": dict(s.get("counts", {})), "nudged": list(s.get("nudged", [])),
            "edits": int(s.get("edits", 0) or 0), "green_at": int(s.get("green_at", -1) or -1)}


def save_state(path, state):
    if len(state["counts"]) > MAX_TRACKED:
        for k in list(state["counts"])[: len(state["counts"]) - MAX_TRACKED]:
            del state["counts"][k]
    state["nudged"] = state["nudged"][-MAX_TRACKED:]
    write_json_atomic(path, state)


def failed(tool_response):
    """Legacy-CLI failure evidence inside a PostToolUse tool_response."""
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
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    d = state_dir()
    prune_stale(d)
    path = os.path.join(d, f"loop-alarm-{scope_slug(data)}.json")
    event = data.get("hook_event_name", "")
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    key = grind_key(tool, tool_input)

    with locked(path):
        state = load_state(path)

        if event == "PreToolUse":
            # Only the Edit grind is counted here (an old_string mismatch fires no
            # post-tool event). Every other PreToolUse is not our business.
            if tool != "Edit" or not key:
                return 0
            n = state["counts"].get(key, 0) + 1
            state["counts"][key] = n
            if n >= threshold() and key not in state["nudged"]:
                state["nudged"].append(key)
                save_state(path, state)
                print(EDIT_NUDGE.format(n=n), file=sys.stderr)
                ledger(data, "loop-alarm", "deny-edit", f"n={n}")
                return 2
            save_state(path, state)
            return 0

        is_failure = event == "PostToolUseFailure" or failed(data.get("tool_response"))
        if is_failure and data.get("is_interrupt") is True:
            return 0  # the user hit Esc — not a failing command

        if not is_failure:
            cmd = norm_cmd(tool_input) if tool in SHELL_TOOLS else ""
            if tool in MODIFYING_TOOLS or (cmd and LOOP_RESET.search(cmd)):
                state["counts"] = {}
                state["edits"] += 1
                save_state(path, state)
                return 0
            if cmd:
                if looks_like_test_run(cmd):
                    state["green_at"] = state["edits"]   # a check passed at this edit count
                state["counts"].pop(key, None)
                save_state(path, state)
            return 0

        if not key:
            return 0
        n = state["counts"].get(key, 0) + 1
        state["counts"][key] = n
        if n >= threshold() and key not in state["nudged"]:
            state["nudged"].append(key)
            save_state(path, state)
            print((EDIT_NUDGE if key.startswith("ed:") else NUDGE).format(n=n), file=sys.stderr)
            ledger(data, "loop-alarm", "nudge", f"{key[:3]}n={n}")
            return 2
        save_state(path, state)
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break a session over a hook bug — fail open
