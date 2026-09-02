# Consistency guards for hooks/hooks.json — the plugin's hook wiring.
# A hook that ships in hooks/ but is absent from hooks.json is silently inert on
# every install; a matcher typo makes it fire on nothing. These pin both.
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
HOOKS_DIR = ROOT / "hooks"

# Event names this Claude Code build dispatches (2.1.258); a name outside this set is
# ignored at runtime with only a validator warning.
KNOWN_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Notification", "UserPromptSubmit",
                "SessionStart", "SessionEnd", "Stop", "SubagentStart", "SubagentStop", "PreCompact",
                "PermissionRequest", "Setup", "TeammateIdle", "TaskCompleted"}


def load_wiring():
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))


def wired(wiring):
    out = []
    for event, groups in wiring.get("hooks", {}).items():
        for group in groups:
            for h in group.get("hooks", []):
                out.append((event, group.get("matcher", ""), h))
    return out


def hook_name(cmd):
    return cmd.rstrip('"').split("/")[-1]


def test_every_shipped_hook_is_wired():
    commands = " ".join(h["command"] for _, _, h in wired(load_wiring()))
    for f in sorted(HOOKS_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue  # shared module, not a hook
        assert f.name in commands, f"{f.name} ships in hooks/ but is not wired in hooks.json"


def test_every_wired_hook_ships():
    for _, _, h in wired(load_wiring()):
        assert (HOOKS_DIR / hook_name(h["command"])).is_file(), h["command"]


def test_commands_use_plugin_root_and_python3():
    for _, _, h in wired(load_wiring()):
        assert h["command"].startswith('python3 "${CLAUDE_PLUGIN_ROOT}/hooks/'), h["command"]
        assert h["type"] == "command"


def test_only_known_events_are_used():
    assert set(load_wiring()["hooks"]) <= KNOWN_EVENTS


def test_hooks_are_wired_to_the_right_events():
    expected = {
        "stop-claim-audit.py": {"Stop"},
        "posttool-loop-alarm.py": {"PreToolUse", "PostToolUse", "PostToolUseFailure"},
        "pretool-destructive-guard.py": {"PreToolUse"},
        "pretool-readonly-agent.py": {"PreToolUse"},
        "pretool-commit-preflight.py": {"PreToolUse"},
        "pretool-workflow-lint.py": {"PreToolUse"},
        "pretool-mem-privacy-guard.py": {"PreToolUse"},
        "precompact-save-task.py": {"PreCompact"},
        "sessionstart-compact-recovery.py": {"SessionStart"},
        "sessionstart-floor-check.py": {"SessionStart"},
        "subagentstop-contract-gate.py": {"SubagentStop"},
        "sessionend-ledger-summary.py": {"SessionEnd"},
    }
    actual = {}
    for e, _, h in wired(load_wiring()):
        actual.setdefault(hook_name(h["command"]), set()).add(e)
    assert actual == expected


def test_load_bearing_matchers_are_pinned():
    by = {}
    for event, matcher, h in wired(load_wiring()):
        by.setdefault((event, hook_name(h["command"])), set()).add(matcher)
    assert by[("SessionStart", "sessionstart-compact-recovery.py")] == {"compact"}
    assert by[("SessionStart", "sessionstart-floor-check.py")] == {"startup|resume|clear|fork"}
    assert by[("PreToolUse", "pretool-destructive-guard.py")] == {"Bash"}
    assert by[("PreToolUse", "pretool-commit-preflight.py")] == {"Bash"}
    assert by[("PreToolUse", "pretool-readonly-agent.py")] == {"Bash|Edit|Write|NotebookEdit"}
    assert by[("PreToolUse", "posttool-loop-alarm.py")] == {"Edit"}
    assert by[("PreToolUse", "pretool-workflow-lint.py")] == {"Workflow"}
    assert by[("PreToolUse", "pretool-mem-privacy-guard.py")] == {"Write|Edit"}
    # The loop alarm must see EVERY tool it counts fail (Edit failures fire this event too).
    assert by[("PostToolUseFailure", "posttool-loop-alarm.py")] == {"Bash|Edit|Write|NotebookEdit"}
    assert by[("PostToolUse", "posttool-loop-alarm.py")] == {"Bash|Edit|Write|NotebookEdit"}
    # Both the plugin-namespaced and bare (a .claude/agents install) ids of the kit agents.
    sub = next(iter(by[("SubagentStop", "subagentstop-contract-gate.py")]))
    for a in ("hardmode:verifier", "hardmode:plan-critic", "hardmode:oracle", "verifier", "plan-critic", "oracle"):
        assert a in sub.split("|")
    for matchers in by.values():
        for m in matchers:
            assert "MultiEdit" not in m and "PowerShell" not in m


def test_matchers_are_exact_membership_lists_not_regexes():
    # Bare alphanumerics (with | and :) are matched by exact membership on this build;
    # anything else becomes an UNANCHORED regex — never rely on that.
    import re
    for _, matcher, _ in wired(load_wiring()):
        assert re.fullmatch(r"[A-Za-z0-9_|:-]*", matcher), matcher


def test_hook_command_is_deduplicated_per_event():
    # The harness dedups hooks by command string within an event: the same hook twice
    # under one event would collapse to one, with an unpredictable matcher.
    seen = {}
    for event, matcher, h in wired(load_wiring()):
        key = (event, h["command"])
        assert key not in seen, f"{h['command']} wired twice under {event}"
        seen[key] = matcher


def test_timeouts_fit_their_events():
    for event, _, h in wired(load_wiring()):
        assert isinstance(h.get("timeout"), int) and h["timeout"] > 0, h
        if event == "SessionEnd":
            assert h["timeout"] <= 4  # SessionEnd races a 5s process-exit timer


def test_settings_reference_carries_no_hooks():
    ref = json.loads((ROOT / "doctrine" / "settings-snippet.json").read_text(encoding="utf-8"))
    assert "hooks" not in ref
    assert ref.get("effortLevel") == "xhigh"
