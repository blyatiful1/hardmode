# Unit tests for the PostToolUse / PostToolUseFailure loop-alarm hook.
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
HOOK = HOOKS / "posttool-loop-alarm.py"


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HOOKS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_hook(state_dir, tool_name, tool_input=None, tool_response=None,
             session="s1", raw_stdin=None, event="PostToolUse"):
    payload = {"session_id": session, "hook_event_name": event, "tool_name": tool_name,
               "tool_input": tool_input or {}, "tool_response": tool_response or {}}
    env = dict(os.environ, HARDMODE_STATE_DIR=str(state_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def fail_bash(state_dir, cmd, **kw):
    # Legacy shape: PostToolUse carrying an explicit non-zero exit code.
    return run_hook(state_dir, "Bash", {"command": cmd}, {"exit_code": 1}, **kw)


def fail_event(state_dir, cmd, **kw):
    # Real 2.1.x shape: a dedicated PostToolUseFailure event with NO exit code.
    return run_hook(state_dir, "Bash", {"command": cmd}, {},
                    event="PostToolUseFailure", **kw)


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


def test_threshold_env_lowers_trip_point(tmp_path):
    # docs/SUCCESSION.md: smaller driver models set HARDMODE_LOOP_THRESHOLD=2.
    env = {"HARDMODE_LOOP_THRESHOLD": "2"}
    payload = {"session_id": "s1", "tool_name": "Bash",
               "tool_input": {"command": "pytest -q"}, "tool_response": {"exit_code": 1}}
    full_env = dict(os.environ, HARDMODE_STATE_DIR=str(tmp_path), **env)
    first = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=30, env=full_env)
    assert first.returncode == 0
    second = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=30, env=full_env)
    assert second.returncode == 2
    assert "LOOP ALARM" in second.stderr


def test_threshold_env_invalid_or_out_of_range_falls_back(tmp_path):
    for i, bad in enumerate(("banana", "1", "0", "99", "")):
        env = dict(os.environ, HARDMODE_STATE_DIR=str(tmp_path / f"state-{i}"),
                   HARDMODE_LOOP_THRESHOLD=bad)
        payload = {"session_id": "s1", "tool_name": "Bash",
                   "tool_input": {"command": "make check"}, "tool_response": {"exit_code": 1}}
        results = [subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                                  capture_output=True, text=True, timeout=30, env=env)
                   for _ in range(3)]
        # falls back to the default of 3: silent, silent, nudge
        assert [r.returncode for r in results] == [0, 0, 2], bad


def test_whitespace_variants_count_as_same_command(tmp_path):
    # "pytest  -q" and "pytest -q" are the same grind; normalization must merge them.
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "pytest    -q")
    r = fail_bash(tmp_path, "pytest \t -q")
    assert r.returncode == 2


def test_different_commands_tracked_independently(tmp_path):
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "npm test")
    fail_bash(tmp_path, "pytest -q")
    assert fail_bash(tmp_path, "npm test").returncode == 0  # only 2 failures each... one more:
    assert fail_bash(tmp_path, "pytest -q").returncode == 2  # pytest reaches 3 first


def test_malformed_stdin_fails_open(tmp_path):
    r = run_hook(tmp_path, "Bash", raw_stdin="not json")
    assert r.returncode == 0


# ---- real Claude Code 2.1.x event model (PostToolUseFailure, no exit code) ----
# THESIS: under the shipped event model a failing Bash command fires
# PostToolUseFailure with no exit-code field, and the alarm must still trip on the
# Nth failure. Before this fix the hook keyed on tool_response.exit_code — a field
# 2.1.x never sends — so it was deterministically inert. These tests are the proof.

def test_failure_event_without_exit_code_still_nudges(tmp_path):
    assert fail_event(tmp_path, "pytest -q").returncode == 0
    assert fail_event(tmp_path, "pytest -q").returncode == 0
    r = fail_event(tmp_path, "pytest -q")
    assert r.returncode == 2
    assert "LOOP ALARM" in r.stderr


def test_failing_write_command_accumulates(tmp_path):
    # CONF0 regression: a failing command that redirects to a file (make test >
    # build.log) used to be read as a legitimizing "file write" and cleared its own
    # count every run, so it never tripped. On the failure event it must accumulate.
    assert fail_event(tmp_path, "make test > build.log").returncode == 0
    assert fail_event(tmp_path, "make test > build.log").returncode == 0
    assert fail_event(tmp_path, "make test > build.log").returncode == 2


def test_successful_postuse_event_resets_without_exit_code(tmp_path):
    # A success now arrives as PostToolUse with no exit code; it must reset the count.
    fail_event(tmp_path, "pytest -q")
    fail_event(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {}, event="PostToolUse")
    assert fail_event(tmp_path, "pytest -q").returncode == 0  # restarted at 1


def test_successful_edit_event_resets_all_counts(tmp_path):
    fail_event(tmp_path, "pytest -q")
    fail_event(tmp_path, "pytest -q")
    run_hook(tmp_path, "Edit", {"file_path": "x.py"}, {}, event="PostToolUse")
    assert fail_event(tmp_path, "pytest -q").returncode == 0


def test_loop_reset_excludes_diagnostic_redirects(tmp_path):
    # The reset trigger must NOT fire on a bare redirect / tee (the model's normal
    # mid-grind "pipe the failing check to a log" move) — that wipe defeated the alarm.
    # It MUST fire on real source mutations (sed -i, Set-Content, mv/cp/patch).
    alarm = _load("posttool-loop-alarm.py")
    gate = _load("stop-claim-audit.py")
    for benign in ("pytest -q 2>&1 | tee out.log", "pytest -q > out.log",
                   "make test >> build.log", "cat x.py"):
        assert not alarm.LOOP_RESET.search(benign), benign
    for mutation in ("sed -i 's/a/b/' x.py", "mv a.py b.py", "cp a.py b.py",
                     "Set-Content -Path x.py -Value 'fix'", "patch < d.diff"):
        assert alarm.LOOP_RESET.search(mutation), mutation
    # MODIFYING_TOOLS still agrees with the claim-audit gate (tool-based reset).
    assert alarm.MODIFYING_TOOLS == gate.MODIFYING_TOOLS


def test_succeeding_tee_does_not_reset_grind_counter(tmp_path):
    # End-to-end proof of the closed hole: two failures, then a SUCCEEDING tee-to-log,
    # then a third failure must still trip — the diagnostic redirect must not reset.
    fail_event(tmp_path, "pytest -q")
    fail_event(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "pytest -q 2>&1 | tee out.log"}, {},
             event="PostToolUse")
    assert fail_event(tmp_path, "pytest -q").returncode == 2

def test_powershell_grind_is_tracked(tmp_path):
    # Native-Windows sessions drive PowerShell as the primary shell; the alarm
    # must count its failures exactly like Bash ones (the Windows snippets wire
    # PostToolUseFailure to Bash|PowerShell).
    for _ in range(2):
        assert run_hook(tmp_path, "PowerShell", {"command": "python -m pytest -q"},
                        {}, event="PostToolUseFailure").returncode == 0
    r = run_hook(tmp_path, "PowerShell", {"command": "python -m pytest -q"},
                 {}, event="PostToolUseFailure")
    assert r.returncode == 2
    assert "LOOP ALARM" in r.stderr


def test_powershell_write_success_resets_counts(tmp_path):
    for _ in range(2):
        run_hook(tmp_path, "PowerShell", {"command": "python -m pytest -q"},
                 {}, event="PostToolUseFailure")
    # A succeeding PowerShell write cmdlet counts as a successful modification.
    run_hook(tmp_path, "PowerShell", {"command": "Set-Content -Path x.py -Value 'fix'"})
    for _ in range(2):
        assert run_hook(tmp_path, "PowerShell", {"command": "python -m pytest -q"},
                        {}, event="PostToolUseFailure").returncode == 0
