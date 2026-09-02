# Unit tests for the loop-alarm hook (PostToolUse / PostToolUseFailure / PreToolUse(Edit)).
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


def base_env(state_dir, **extra):
    env = dict(os.environ, HARDMODE_STATE_DIR=str(state_dir))
    env.pop("HARDMODE_LOOP_THRESHOLD", None)   # the operator's knob must not leak into tests
    env.update(extra)
    return env


def run_hook(state_dir, tool_name, tool_input=None, tool_response=None,
             session="s1", raw_stdin=None, event="PostToolUse", agent_id=None, **fields):
    payload = {"session_id": session, "hook_event_name": event, "tool_name": tool_name,
               "tool_input": tool_input or {}, "tool_response": tool_response or {}}
    if agent_id:
        payload["agent_id"] = agent_id
    payload.update(fields)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=base_env(state_dir),
    )


def fail_bash(state_dir, cmd, **kw):
    # Legacy shape: PostToolUse carrying an explicit non-zero exit code.
    return run_hook(state_dir, "Bash", {"command": cmd}, {"exit_code": 1}, **kw)


def fail_event(state_dir, cmd, **kw):
    # Real 2.1.x shape: a dedicated PostToolUseFailure event with NO exit code.
    return run_hook(state_dir, "Bash", {"command": cmd}, {}, event="PostToolUseFailure", **kw)


def edit_attempt(state_dir, file_path, old_string, **kw):
    return run_hook(state_dir, "Edit", {"file_path": file_path, "old_string": old_string,
                                        "new_string": "x"}, {}, event="PreToolUse", **kw)


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
    assert fail_bash(tmp_path, "pytest -q").returncode == 0


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
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "cat src/parser.py"}, {"exit_code": 0})
    fail_bash(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "grep -n foo src/parser.py"}, {"exit_code": 0})
    assert fail_bash(tmp_path, "pytest -q").returncode == 2


def test_unknown_exit_code_never_counts(tmp_path):
    for _ in range(4):
        assert run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {"stdout": "boom"}).returncode == 0


def test_is_error_counts_as_failure(tmp_path):
    for _ in range(2):
        run_hook(tmp_path, "Bash", {"command": "npm test"}, {"is_error": True})
    assert run_hook(tmp_path, "Bash", {"command": "npm test"}, {"is_error": True}).returncode == 2


def test_sessions_are_isolated(tmp_path):
    fail_bash(tmp_path, "pytest -q", session="a")
    fail_bash(tmp_path, "pytest -q", session="a")
    assert fail_bash(tmp_path, "pytest -q", session="b").returncode == 0


def test_subagents_do_not_share_the_parent_counter(tmp_path):
    # Subagents carry the parent's session_id plus their own agent_id; a parallel
    # agent's failures must not push the main thread (or a sibling) over the threshold.
    fail_event(tmp_path, "pytest -q", agent_id="agent-a")
    fail_event(tmp_path, "pytest -q", agent_id="agent-a")
    assert fail_event(tmp_path, "pytest -q").returncode == 0
    assert fail_event(tmp_path, "pytest -q", agent_id="agent-b").returncode == 0
    assert fail_event(tmp_path, "pytest -q", agent_id="agent-a").returncode == 2


def test_threshold_env_lowers_trip_point(tmp_path):
    payload = {"session_id": "s1", "tool_name": "Bash", "hook_event_name": "PostToolUseFailure",
               "tool_input": {"command": "pytest -q"}, "tool_response": {}}
    env = base_env(tmp_path, HARDMODE_LOOP_THRESHOLD="2")
    first = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=30, env=env)
    assert first.returncode == 0
    second = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=30, env=env)
    assert second.returncode == 2
    assert "LOOP ALARM" in second.stderr


def test_threshold_env_invalid_or_out_of_range_falls_back(tmp_path):
    for i, bad in enumerate(("banana", "1", "0", "99", "")):
        env = base_env(tmp_path / f"state-{i}", HARDMODE_LOOP_THRESHOLD=bad)
        payload = {"session_id": "s1", "tool_name": "Bash", "hook_event_name": "PostToolUseFailure",
                   "tool_input": {"command": "make check"}, "tool_response": {}}
        results = [subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                                  capture_output=True, text=True, timeout=30, env=env)
                   for _ in range(3)]
        assert [r.returncode for r in results] == [0, 0, 2], bad


def test_whitespace_variants_count_as_same_command(tmp_path):
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "pytest    -q")
    assert fail_bash(tmp_path, "pytest \t -q").returncode == 2


def test_different_commands_tracked_independently(tmp_path):
    fail_bash(tmp_path, "pytest -q")
    fail_bash(tmp_path, "npm test")
    fail_bash(tmp_path, "pytest -q")
    assert fail_bash(tmp_path, "npm test").returncode == 0
    assert fail_bash(tmp_path, "pytest -q").returncode == 2


def test_malformed_stdin_fails_open(tmp_path):
    assert run_hook(tmp_path, "Bash", raw_stdin="not json").returncode == 0


# ---- real Claude Code 2.1.x event model (PostToolUseFailure, no exit code) ----

def test_failure_event_without_exit_code_still_nudges(tmp_path):
    assert fail_event(tmp_path, "pytest -q").returncode == 0
    assert fail_event(tmp_path, "pytest -q").returncode == 0
    r = fail_event(tmp_path, "pytest -q")
    assert r.returncode == 2
    assert "LOOP ALARM" in r.stderr


def test_failing_write_command_accumulates(tmp_path):
    assert fail_event(tmp_path, "make test > build.log").returncode == 0
    assert fail_event(tmp_path, "make test > build.log").returncode == 0
    assert fail_event(tmp_path, "make test > build.log").returncode == 2


def test_successful_postuse_event_resets_without_exit_code(tmp_path):
    fail_event(tmp_path, "pytest -q")
    fail_event(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {}, event="PostToolUse")
    assert fail_event(tmp_path, "pytest -q").returncode == 0


def test_successful_edit_event_resets_all_counts(tmp_path):
    fail_event(tmp_path, "pytest -q")
    fail_event(tmp_path, "pytest -q")
    run_hook(tmp_path, "Edit", {"file_path": "x.py"}, {}, event="PostToolUse")
    assert fail_event(tmp_path, "pytest -q").returncode == 0


def test_loop_reset_excludes_diagnostic_redirects(tmp_path):
    alarm = _load("posttool-loop-alarm.py")
    gate = _load("stop-claim-audit.py")
    for benign in ("pytest -q 2>&1 | tee out.log", "pytest -q > out.log",
                   "make test >> build.log", "cat x.py"):
        assert not alarm.LOOP_RESET.search(benign), benign
    for mutation in ("sed -i 's/a/b/' x.py", "mv a.py b.py", "cp a.py b.py", "patch < d.diff"):
        assert alarm.LOOP_RESET.search(mutation), mutation
    assert alarm.MODIFYING_TOOLS == gate.MODIFYING_TOOLS


def test_succeeding_tee_does_not_reset_grind_counter(tmp_path):
    fail_event(tmp_path, "pytest -q")
    fail_event(tmp_path, "pytest -q")
    run_hook(tmp_path, "Bash", {"command": "pytest -q 2>&1 | tee out.log"}, {}, event="PostToolUse")
    assert fail_event(tmp_path, "pytest -q").returncode == 2


def test_user_interrupt_is_not_a_failure(tmp_path):
    for _ in range(4):
        r = fail_event(tmp_path, "pytest -q", is_interrupt=True)
        assert r.returncode == 0
    assert fail_event(tmp_path, "pytest -q").returncode == 0   # count starts at 1 now


# ---- the Edit grind (PreToolUse) ----

def test_third_identical_edit_is_denied_with_a_nudge(tmp_path):
    assert edit_attempt(tmp_path, "/w/x.py", "def foo():").returncode == 0
    assert edit_attempt(tmp_path, "/w/x.py", "def foo():").returncode == 0
    r = edit_attempt(tmp_path, "/w/x.py", "def foo():")
    assert r.returncode == 2
    assert "LOOP ALARM" in r.stderr and "old_string" in r.stderr


def test_different_edits_are_not_a_grind(tmp_path):
    assert edit_attempt(tmp_path, "/w/x.py", "def foo():").returncode == 0
    assert edit_attempt(tmp_path, "/w/x.py", "def bar():").returncode == 0
    assert edit_attempt(tmp_path, "/w/y.py", "def foo():").returncode == 0
    assert edit_attempt(tmp_path, "/w/x.py", "def foo():").returncode == 0


def test_successful_edit_clears_the_edit_grind(tmp_path):
    edit_attempt(tmp_path, "/w/x.py", "def foo():")
    edit_attempt(tmp_path, "/w/x.py", "def foo():")
    run_hook(tmp_path, "Edit", {"file_path": "/w/x.py", "old_string": "def foo():"}, {},
             event="PostToolUse")
    assert edit_attempt(tmp_path, "/w/x.py", "def foo():").returncode == 0


def test_runtime_edit_failures_count_too(tmp_path):
    # A stale-read Edit failure DOES fire PostToolUseFailure on 2.1.x; it must accumulate
    # under the same key as the PreToolUse attempts.
    payload = {"file_path": "/w/x.py", "old_string": "a", "new_string": "b"}
    run_hook(tmp_path, "Edit", payload, {}, event="PostToolUseFailure",
             error="File content has changed since it was last read")
    run_hook(tmp_path, "Edit", payload, {}, event="PostToolUseFailure",
             error="File content has changed since it was last read")
    assert edit_attempt(tmp_path, "/w/x.py", "a").returncode == 2


def test_other_pretooluse_events_are_ignored(tmp_path):
    for _ in range(5):
        assert run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {}, event="PreToolUse").returncode == 0
        assert run_hook(tmp_path, "Write", {"file_path": "/w/x.py", "content": "x"}, {},
                        event="PreToolUse").returncode == 0


# ---- state hygiene ----

def test_state_stores_hashes_not_command_text(tmp_path):
    fail_event(tmp_path, "curl -u admin:hunter2 https://internal.example.com/x")
    state = json.loads((tmp_path / "loop-alarm-s1.json").read_text(encoding="utf-8"))
    dumped = json.dumps(state)
    assert "hunter2" not in dumped and "internal.example.com" not in dumped
    assert all(k.startswith(("sh:", "ed:", "wr:")) for k in state["counts"])


def test_state_files_are_private(tmp_path):
    fail_event(tmp_path, "pytest -q")
    mode = (tmp_path / "loop-alarm-s1.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_green_check_and_edit_counters_feed_the_preflight(tmp_path):
    run_hook(tmp_path, "Edit", {"file_path": "x.py"}, {}, event="PostToolUse")
    run_hook(tmp_path, "Edit", {"file_path": "y.py"}, {}, event="PostToolUse")
    state = json.loads((tmp_path / "loop-alarm-s1.json").read_text(encoding="utf-8"))
    assert state["edits"] == 2 and state["green_at"] == -1
    run_hook(tmp_path, "Bash", {"command": "pytest -q"}, {}, event="PostToolUse")
    state = json.loads((tmp_path / "loop-alarm-s1.json").read_text(encoding="utf-8"))
    assert state["green_at"] == 2
    run_hook(tmp_path, "Bash", {"command": "sed -i s/a/b/ z.py"}, {}, event="PostToolUse")
    state = json.loads((tmp_path / "loop-alarm-s1.json").read_text(encoding="utf-8"))
    assert state["edits"] == 3 and state["green_at"] == 2


def test_nudge_is_written_to_the_ledger(tmp_path):
    for _ in range(3):
        fail_event(tmp_path, "pytest -q")
    recs = [json.loads(ln) for ln in (tmp_path / "ledger-s1.jsonl").read_text().splitlines()]
    assert any(r["hook"] == "loop-alarm" and r["outcome"] == "nudge" for r in recs)
