# Unit tests for the PostToolUse loop-alarm hook.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "claude" / "hooks" / "posttool-loop-alarm.py"


def run_hook(state_dir, tool_name, tool_input=None, tool_response=None,
             session="s1", raw_stdin=None):
    payload = {"session_id": session, "tool_name": tool_name,
               "tool_input": tool_input or {}, "tool_response": tool_response or {}}
    env = dict(os.environ, FABLE_STATE_DIR=str(state_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def fail_bash(state_dir, cmd, **kw):
    return run_hook(state_dir, "Bash", {"command": cmd}, {"exit_code": 1}, **kw)


def test_third_identical_failure_nudges(tmp_path):
    assert fail_bash(tmp_path, "pytest -q").returncode == 0
    assert fail_bash(tmp_path, "pytest -q").returncode == 0
    r = fail_bash(tmp_path, "pytest -q")
    assert r.returncode == 2
    assert "LOOP ALARM" in r.stderr


def test_nudges_only_once_per_command(tmp_path):
    for _ in range(3):
        fail_bash(tmp_path, "make test")
    assert fail_bash(tmp_path, "make test").returncode == 0


def test_success_resets_count(tmp_path):
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {"exit_code": 0})
    assert fail_bash(tmp_path, "pytest -q").returncode == 0  # count restarted at 1


def test_file_edit_resets_all_counts(tmp_path):
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Edit", {"file_path": "x.py"})
    assert fail_bash(tmp_path, "pytest -q").returncode == 0


def test_bash_write_resets_counts(tmp_path):
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "sed -i 's/a/b/' x.py"}, {"exit_code": 0})
    assert fail_bash(tmp_path, "pytest -q").returncode == 0


def test_interleaved_reads_do_not_reset(tmp_path):
    # The classic grind: run check, read code, run check, read code, run check.
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "cat src/parser.py"}, {"exit_code": 0})
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "grep -n foo src/parser.py"}, {"exit_code": 0})
    assert fail_bash(tmp_path, "pytest -q").returncode == 2


def test_unknown_exit_code_never_counts(tmp_path):
    for _ in range(4):
        r = run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {"stdout": "boom"})
        assert r.returncode == 0


def test_is_error_counts_as_failure(tmp_path):
    for _ in range(2):
        run_hook(tmp_path, "Bash", {"command": "npm test"}, {"is_error": True})
    r = run_hook(tmp_path, "Bash", {"command": "npm test"}, {"is_error": True})
    assert r.returncode == 2


def test_sessions_are_isolated(tmp_path):
    fail_bash(tmp_path, "pytest -q", session="a")
    fail_bash(tmp_path, "pytest -q", session="a")
    assert fail_bash(tmp_path, "pytest -q", session="b").returncode == 0


def test_malformed_stdin_fails_open(tmp_path):
    r = run_hook(tmp_path, "Bash", raw_stdin="not json")
    assert r.returncode == 0
