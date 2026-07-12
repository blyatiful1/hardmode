# Consistency guards for the settings snippet — the kit's single manual step.
# A hook that ships in claude/hooks/ but is absent from the snippet is silently
# inert on every install; this is the regression that would cause it.
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "claude" / "settings" / "settings-snippet.json"
HOOKS_DIR = ROOT / "claude" / "hooks"


def load_snippet():
    return json.loads(SNIPPET.read_text())


def wired_commands(snippet):
    cmds = []
    for event, groups in snippet.get("hooks", {}).items():
        for group in groups:
            for h in group.get("hooks", []):
                cmds.append((event, group.get("matcher", ""), h.get("command", "")))
    return cmds


def test_every_shipped_hook_is_wired():
    commands = " ".join(c for _, _, c in wired_commands(load_snippet()))
    for f in sorted(HOOKS_DIR.glob("*.py")):
        assert f.name in commands, f"{f.name} ships in claude/hooks/ but is not wired in the snippet"


def test_every_wired_hook_ships():
    for _, _, cmd in wired_commands(load_snippet()):
        name = cmd.split("/")[-1]
        assert (HOOKS_DIR / name).is_file(), f"snippet wires {name} but claude/hooks/ does not ship it"


def test_hooks_are_wired_to_the_right_events():
    # Each hook -> the SET of events it is wired to. The loop alarm needs BOTH
    # PostToolUse (to observe the successes that reset the grind counter) and
    # PostToolUseFailure (the only event that carries a Bash failure in 2.1.x).
    expected = {
        "stop-claim-audit.py": {"Stop"},
        "posttool-loop-alarm.py": {"PostToolUse", "PostToolUseFailure"},
        "posttool-test-weakening-alarm.py": {"PostToolUse"},
        "pretool-destructive-guard.py": {"PreToolUse"},
        "precompact-save-task.py": {"PreCompact"},
        "sessionstart-compact-recovery.py": {"SessionStart"},
        "userpromptsubmit-mem-recall.py": {"UserPromptSubmit"},
        "sessionend-mem-journal.py": {"SessionEnd"},
        "pretool-mem-privacy-guard.py": {"PreToolUse"},
    }
    actual = {}
    for e, _, c in wired_commands(load_snippet()):
        actual.setdefault(c.split("/")[-1], set()).add(e)
    assert actual == expected


def test_load_bearing_matchers_are_pinned():
    # Matchers are load-bearing, not cosmetic: SessionStart must scope to 'compact'
    # (a bare match would fire on every session start), the destructive guard and the
    # failure-side loop alarm must scope to Bash, and the recovery hooks must not.
    by = {}
    for event, matcher, cmd in wired_commands(load_snippet()):
        by[(event, cmd.split("/")[-1])] = matcher
    assert by[("SessionStart", "sessionstart-compact-recovery.py")] == "compact"
    assert by[("PreToolUse", "pretool-destructive-guard.py")] == "Bash"
    assert by[("PostToolUseFailure", "posttool-loop-alarm.py")] == "Bash"
    # MultiEdit was removed from Claude Code 2.1.x — no matcher should still name it.
    for matcher in by.values():
        assert "MultiEdit" not in matcher


def test_weakening_alarm_matcher_covers_edit_tools_only():
    # It reads old_string/new_string/content — Bash payloads have neither, and a
    # Bash matcher would burn a hook invocation on every command for nothing.
    for _, matcher, cmd in wired_commands(load_snippet()):
        if "test-weakening" in cmd:
            for tool in ("Edit", "Write"):
                assert tool in matcher
            assert "Bash" not in matcher


def test_effort_level_is_xhigh():
    assert load_snippet().get("effortLevel") == "xhigh"
