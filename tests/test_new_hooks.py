# Tests for the session-end ledger rollup, the session-start floor check, the commit
# preflight and the Workflow pre-flight lint.
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"


def run(hook, payload, env_extra=None, raw=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(HOOKS / hook)], input=raw if raw is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=90, env=env)


def ledger_line(hook, outcome, detail=""):
    return json.dumps({"ts": 1, "hook": hook, "event": "x", "outcome": outcome, "detail": detail, "agent": ""})


# ---- SessionEnd ledger rollup ----

def test_sessionend_rolls_the_ledger_into_sessions_jsonl(tmp_path):
    (tmp_path / "ledger-s1.jsonl").write_text("\n".join([
        ledger_line("claim-audit", "block", "no-check"), ledger_line("claim-audit", "pass", "evidence"),
        ledger_line("destructive-guard", "block", "reset-hard"), ledger_line("floor-check", "ran")]) + "\n")
    r = run("sessionend-ledger-summary.py", {"session_id": "s1", "reason": "other", "cwd": "/w",
                                             "hook_event_name": "SessionEnd"}, {"HARDMODE_STATE_DIR": str(tmp_path)})
    assert r.returncode == 0 and r.stdout == ""
    rec = json.loads((tmp_path / "sessions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["session"] == "s1" and rec["reason"] == "other" and rec["events"] == 4
    assert rec["by_hook"] == {"claim-audit:block": 1, "claim-audit:pass": 1, "destructive-guard:block": 1, "floor-check:ran": 1}


def test_sessionend_without_ledger_still_records_the_session(tmp_path):
    run("sessionend-ledger-summary.py", {"session_id": "quiet", "reason": "clear"}, {"HARDMODE_STATE_DIR": str(tmp_path)})
    rec = json.loads((tmp_path / "sessions.jsonl").read_text().strip())
    assert rec["events"] == 0 and rec["by_hook"] == {}


def test_sessionend_rotates_to_500_lines(tmp_path):
    (tmp_path / "sessions.jsonl").write_text("\n".join(json.dumps({"session": f"old{i}"}) for i in range(505)) + "\n")
    run("sessionend-ledger-summary.py", {"session_id": "new"}, {"HARDMODE_STATE_DIR": str(tmp_path)})
    lines = (tmp_path / "sessions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 500 and json.loads(lines[-1])["session"] == "new"
    assert run("sessionend-ledger-summary.py", {}, {"HARDMODE_STATE_DIR": str(tmp_path)}, raw="nope").returncode == 0


# ---- SessionStart floor check ----

def fake_claude(tmp_path, content="#!/bin/sh\necho 2.1.258\n"):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    exe = b / "claude"
    exe.write_text(content)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return b


def floor_env(tmp_path, **extra):
    env = {"HARDMODE_STATE_DIR": str(tmp_path / "state"), "PATH": f"{fake_claude(tmp_path)}:{os.environ.get('PATH', '')}"}
    env.update(extra)
    return env


def test_floor_check_witnesses_itself_and_is_silent_when_nothing_fired(tmp_path):
    env = floor_env(tmp_path, HARDMODE_SELFTEST="0")
    r = run("sessionstart-floor-check.py", {"session_id": "s2", "source": "startup", "hook_event_name": "SessionStart"}, env)
    assert r.returncode == 0 and r.stdout.strip() == ""
    recs = [json.loads(ln) for ln in (tmp_path / "state" / "ledger-s2.jsonl").read_text().splitlines()]
    assert recs[0]["hook"] == "floor-check" and recs[0]["outcome"] == "ran"


def test_floor_check_relays_what_fired_last_session(tmp_path):
    env = floor_env(tmp_path, HARDMODE_SELFTEST="0")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "sessions.jsonl").write_text(json.dumps({
        "session": "prev", "by_hook": {"claim-audit:block": 1, "loop-alarm:nudge": 2, "floor-check:ran": 1}}) + "\n")
    r = run("sessionstart-floor-check.py", {"session_id": "s3", "source": "resume"}, env)
    assert "previous session" in r.stdout and "claim-audit block x1" in r.stdout and "loop-alarm nudge x2" in r.stdout
    assert "floor-check" not in r.stdout


def test_floor_check_never_runs_on_compact(tmp_path):
    env = floor_env(tmp_path, HARDMODE_SELFTEST="0")
    r = run("sessionstart-floor-check.py", {"session_id": "s4", "source": "compact"}, env)
    assert r.returncode == 0 and r.stdout == "" and not (tmp_path / "state" / "ledger-s4.jsonl").exists()


def test_floor_check_self_tests_the_real_hooks_when_the_binary_changes(tmp_path):
    env = floor_env(tmp_path)
    r = run("sessionstart-floor-check.py", {"session_id": "s5", "source": "startup"}, env)
    assert r.returncode == 0
    assert "hook self-test OK" in r.stdout and "scenarios behaved as expected" in r.stdout
    assert (tmp_path / "state" / "harness-fp.txt").exists()
    # unchanged binary: silent
    r = run("sessionstart-floor-check.py", {"session_id": "s6", "source": "startup"}, env)
    assert r.stdout.strip() == ""
    # a changed binary triggers the self-test again
    fake_claude(tmp_path, "#!/bin/sh\necho 2.1.300 with more bytes\n")
    r = run("sessionstart-floor-check.py", {"session_id": "s7", "source": "startup"}, env)
    assert "hook self-test OK" in r.stdout


def test_floor_check_reports_a_degraded_floor(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "tools").mkdir(parents=True)
    (plugin / "tools" / "demo.py").write_text(
        "import sys\nprint('SCENARIO 1  x')\nprint('  [FAIL] claim-audit false claim: expected exit 2, got 0')\n"
        "print('demo: 4/5 scenarios behaved as expected')\nsys.exit(1)\n")
    env = floor_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(plugin))
    r = run("sessionstart-floor-check.py", {"session_id": "s8", "source": "startup"}, env)
    assert "HARDMODE FLOOR DEGRADED" in r.stdout and "claim-audit false claim" in r.stdout and "4/5" in r.stdout


def test_floor_check_does_not_remember_a_binary_whose_self_test_failed(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "tools").mkdir(parents=True)
    (plugin / "tools" / "demo.py").write_text(
        "import sys\nprint('  [FAIL] claim-audit false claim: expected exit 2, got 0')\n"
        "print('demo: 4/5 scenarios behaved as expected')\nsys.exit(1)\n")
    env = floor_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(plugin))
    r = run("sessionstart-floor-check.py", {"session_id": "f1", "source": "startup"}, env)
    assert "HARDMODE FLOOR DEGRADED" in r.stdout and "first session on this machine" in r.stdout
    assert not (tmp_path / "state" / "harness-fp.txt").exists()
    # same binary, next session: re-tested and re-announced, not silently accepted
    r = run("sessionstart-floor-check.py", {"session_id": "f2", "source": "resume"}, env)
    assert "HARDMODE FLOOR DEGRADED" in r.stdout


def test_floor_check_wording_distinguishes_first_run_from_a_changed_binary(tmp_path):
    env = floor_env(tmp_path)
    r = run("sessionstart-floor-check.py", {"session_id": "f3", "source": "startup"}, env)
    assert "first session on this machine" in r.stdout and "binary changed" not in r.stdout
    fake_claude(tmp_path, "#!/bin/sh\necho 2.1.300 with more bytes\n")
    r = run("sessionstart-floor-check.py", {"session_id": "f4", "source": "startup"}, env)
    assert "Claude Code binary changed" in r.stdout and "first session" not in r.stdout


def test_floor_check_puts_the_degraded_notice_first_and_caps_it(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "tools").mkdir(parents=True)
    fails = "\n".join(f"print('  [FAIL] scenario-{i}: expected exit 2, got 0 ' + 'x' * 80)" for i in range(30))
    (plugin / "tools" / "demo.py").write_text(f"import sys\n{fails}\nprint('demo: 0/30 scenarios behaved as expected')\nsys.exit(1)\n")
    env = floor_env(tmp_path, CLAUDE_PLUGIN_ROOT=str(plugin))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "sessions.jsonl").write_text(json.dumps({"session": "prev", "by_hook": {"claim-audit:block": 1}}) + "\n")
    r = run("sessionstart-floor-check.py", {"session_id": "f5", "source": "startup"}, env)
    lines = r.stdout.rstrip("\n").split("\n")
    assert lines[0].startswith("HARDMODE FLOOR DEGRADED") and len(lines[0]) <= 700
    assert "previous session" in lines[-1] and "claim-audit block x1" in lines[-1]


def test_prune_keeps_the_cross_session_files(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("hm", HOOKS / "_hardmode.py")
    hm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hm)
    old = 1_000_000
    for name in ("ledger-old.jsonl", "loop-alarm-old.json", "claim-gate-old.json", "original-task-old.txt",
                 "compact-turns-old.txt", "sessions.jsonl", "harness-fp.txt", "unrelated.txt"):
        f = tmp_path / name
        f.write_text("x")
        os.utime(f, (old, old))
    (tmp_path / "ledger-fresh.jsonl").write_text("x")
    hm.prune_stale(str(tmp_path))
    left = {p.name for p in tmp_path.iterdir()}
    assert left == {"ledger-fresh.jsonl", "sessions.jsonl", "harness-fp.txt", "unrelated.txt"}


# ---- commit preflight ----

def state(tmp_path, edits, green_at, scope="s1"):
    (tmp_path / f"loop-alarm-{scope}.json").write_text(json.dumps({"counts": {}, "nudged": [], "edits": edits, "green_at": green_at}))


def preflight(tmp_path, cmd, env_extra=None, **fields):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "session_id": "s1", "hook_event_name": "PreToolUse"}
    payload.update(fields)
    env = {"HARDMODE_STATE_DIR": str(tmp_path)}
    env.update(env_extra or {})
    return run("pretool-commit-preflight.py", payload, env)


def test_preflight_nudges_when_edits_landed_after_the_last_green_check(tmp_path):
    state(tmp_path, edits=3, green_at=-1)
    r = preflight(tmp_path, 'git commit -m "wip"')
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "PREFLIGHT" in out["hookSpecificOutput"]["additionalContext"] and "no recognised check has passed" in out["hookSpecificOutput"]["additionalContext"]
    state(tmp_path, edits=5, green_at=3)
    r = preflight(tmp_path, "git push -u origin main")
    assert "2 modification(s) landed after the last passing check" in r.stdout


def test_preflight_is_silent_when_the_check_is_green_or_nothing_changed(tmp_path):
    state(tmp_path, edits=3, green_at=3)
    assert preflight(tmp_path, 'git commit -m x').stdout == ""
    state(tmp_path, edits=0, green_at=-1)
    assert preflight(tmp_path, 'git commit -m x').stdout == ""
    state(tmp_path, edits=3, green_at=-1)
    for cmd in ("git status", "git diff", 'echo "git commit later"', "ls", "git log --oneline"):
        assert preflight(tmp_path, cmd).stdout == "", cmd


def test_preflight_modes(tmp_path):
    state(tmp_path, edits=3, green_at=-1)
    r = preflight(tmp_path, "git commit -m x", {"HARDMODE_PREFLIGHT": "block"})
    assert r.returncode == 2 and "PREFLIGHT" in r.stderr
    r = preflight(tmp_path, "git commit -m x", {"HARDMODE_PREFLIGHT": "off"})
    assert r.returncode == 0 and r.stdout == ""


def test_preflight_aggregates_subagent_edits_on_the_main_thread(tmp_path):
    # Edits delegated to a subagent are exactly the ones nobody re-checked: a commit on
    # the main thread sees them. Inside the subagent, only its own scope counts.
    state(tmp_path, edits=3, green_at=-1, scope="s1-a1")
    assert "PREFLIGHT" in preflight(tmp_path, "git commit -m x").stdout
    assert "PREFLIGHT" in preflight(tmp_path, "git commit -m x", agent_id="a1").stdout
    assert preflight(tmp_path, "git commit -m x", agent_id="a2").stdout == ""
    # a passing check on the main thread does not launder the subagent's unchecked edits
    state(tmp_path, edits=2, green_at=2)
    r = preflight(tmp_path, "git commit -m x")
    assert "3 modification(s) landed after the last passing check" in r.stdout
    # ...but the subagent's own green check does
    state(tmp_path, edits=3, green_at=3, scope="s1-a1")
    assert preflight(tmp_path, "git commit -m x").stdout == ""
    # another session's files never leak in
    state(tmp_path, edits=9, green_at=-1, scope="s2")
    assert preflight(tmp_path, "git commit -m x").stdout == ""


def test_preflight_sees_through_global_git_options_and_newlines(tmp_path):
    state(tmp_path, edits=3, green_at=-1)
    for cmd in ("git -C /repo commit -m x", "git -c core.autocrlf=false commit -am x", "git --no-pager commit -m x",
                "echo done\ngit commit -m x", "git add -A && git commit -m x", "cd sub; git push"):
        assert "PREFLIGHT" in preflight(tmp_path, cmd).stdout, cmd
    for cmd in ('echo "git commit -m x"', "git log --grep 'commit'", "git commit-tree HEAD^{tree}", "grep -rn 'git push' docs/"):
        assert preflight(tmp_path, cmd).stdout == "", cmd


# ---- workflow pre-flight lint ----

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_workflow_lint_denies_a_script_that_breaks_the_rules(tmp_path):
    bad = "export const meta = { name: 'x', description: 'y' }\nconst r = await agent('do it')\nreturn r"
    r = run("pretool-workflow-lint.py", {"tool_name": "Workflow", "tool_input": {"script": bad}, "session_id": "w"},
            {"HARDMODE_STATE_DIR": str(tmp_path)})
    assert r.returncode == 2 and "WORKFLOW LINT" in r.stderr and "model" in r.stderr


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_workflow_lint_passes_a_clean_script_and_ignores_other_inputs(tmp_path):
    good = "export const meta = { name: 'x', description: 'y' }\nconst r = await agent('do it', { model: 'opus' })\nreturn r"
    env = {"HARDMODE_STATE_DIR": str(tmp_path)}
    assert run("pretool-workflow-lint.py", {"tool_name": "Workflow", "tool_input": {"script": good}}, env).returncode == 0
    assert run("pretool-workflow-lint.py", {"tool_name": "Workflow", "tool_input": {"name": "hardmode:bug-hunt"}}, env).returncode == 0
    assert run("pretool-workflow-lint.py", {"tool_name": "Bash", "tool_input": {"command": "agent()"}}, env).returncode == 0
    assert run("pretool-workflow-lint.py", {}, env, raw="nope").returncode == 0
