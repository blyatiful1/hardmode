# Consistency guards for hooks/hooks.json — the plugin's hook wiring.
# A hook that ships in hooks/ but is absent from hooks.json is silently inert
# on every install; this is the regression that would cause it.
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
HOOKS_DIR = ROOT / "hooks"


def load_wiring():
    return json.loads(HOOKS_JSON.read_text())


def wired_commands(wiring):
    cmds = []
    for event, groups in wiring.get("hooks", {}).items():
        for group in groups:
            for h in group.get("hooks", []):
                cmds.append((event, group.get("matcher", ""), h.get("command", "")))
    return cmds


def hook_name(cmd):
    # command form: python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py"
    return cmd.rstrip('"').split("/")[-1]


def test_every_shipped_hook_is_wired():
    commands = " ".join(c for _, _, c in wired_commands(load_wiring()))
    for f in sorted(HOOKS_DIR.glob("*.py")):
        assert f.name in commands, f"{f.name} ships in hooks/ but is not wired in hooks.json"


def test_every_wired_hook_ships():
    for _, _, cmd in wired_commands(load_wiring()):
        name = hook_name(cmd)
        assert (HOOKS_DIR / name).is_file(), f"hooks.json wires {name} but hooks/ does not ship it"


def test_commands_use_plugin_root_and_python3():
    # ${CLAUDE_PLUGIN_ROOT} makes the wiring location-independent; bare `python`
    # is the classic never-fires mistake on POSIX boxes.
    for _, _, cmd in wired_commands(load_wiring()):
        assert cmd.startswith('python3 "${CLAUDE_PLUGIN_ROOT}/hooks/'), cmd


def test_hooks_are_wired_to_the_right_events():
    # The loop alarm needs BOTH PostToolUse (to observe the successes that reset
    # the grind counter) and PostToolUseFailure (the only event that carries a
    # Bash failure in 2.1.x).
    expected = {
        "stop-claim-audit.py": {"Stop"},
        "posttool-loop-alarm.py": {"PostToolUse", "PostToolUseFailure"},
        "pretool-destructive-guard.py": {"PreToolUse"},
        "precompact-save-task.py": {"PreCompact"},
        "sessionstart-compact-recovery.py": {"SessionStart"},
        "pretool-mem-privacy-guard.py": {"PreToolUse"},
    }
    actual = {}
    for e, _, c in wired_commands(load_wiring()):
        actual.setdefault(hook_name(c), set()).add(e)
    assert actual == expected


def test_load_bearing_matchers_are_pinned():
    # Matchers are load-bearing, not cosmetic: SessionStart must scope to 'compact'
    # (a bare match would fire on every session start), the destructive guard and
    # the failure-side loop alarm must scope to Bash.
    by = {}
    for event, matcher, cmd in wired_commands(load_wiring()):
        by[(event, hook_name(cmd))] = matcher
    assert by[("SessionStart", "sessionstart-compact-recovery.py")] == "compact"
    assert by[("PreToolUse", "pretool-destructive-guard.py")] == "Bash"
    assert by[("PostToolUseFailure", "posttool-loop-alarm.py")] == "Bash"
    # MultiEdit was removed from Claude Code 2.1.x — no matcher should still name it.
    for matcher in by.values():
        assert "MultiEdit" not in matcher


def test_settings_reference_carries_no_hooks():
    # Hook wiring is plugin-owned now. The doctrine settings reference exists only
    # for the keys a plugin cannot set (effortLevel, env) — if hooks reappear
    # there, two wirings will double-fire every event.
    ref = json.loads((ROOT / "doctrine" / "settings-snippet.json").read_text())
    assert "hooks" not in ref
    assert ref.get("effortLevel") == "xhigh"
