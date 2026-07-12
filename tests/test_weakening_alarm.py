# Unit tests for the PostToolUse test-weakening alarm.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "claude" / "hooks" / "posttool-test-weakening-alarm.py"


def run_hook(state_dir, tool_name, tool_input, session="s1", raw_stdin=None):
    payload = {"session_id": session, "tool_name": tool_name, "tool_input": tool_input}
    env = dict(os.environ, FABLE_STATE_DIR=str(state_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def edit(state_dir, path, old, new, **kw):
    return run_hook(state_dir, "Edit",
                    {"file_path": path, "old_string": old, "new_string": new}, **kw)


def test_adding_pytest_skip_to_test_file_alarms(tmp_path):
    r = edit(tmp_path, "tests/test_parser.py",
             "def test_empty():", "@pytest.mark.skip(reason='flaky')\ndef test_empty():")
    assert r.returncode == 2
    assert "TEST-WEAKENING ALARM" in r.stderr


def test_adding_xfail_alarms(tmp_path):
    r = edit(tmp_path, "tests/test_parser.py",
             "def test_x():", "@pytest.mark.xfail\ndef test_x():")
    assert r.returncode == 2


def test_jest_skip_variants_alarm(tmp_path):
    for new in ("it.skip('parses', () => {", "test.skip('parses'", "xit('parses'",
                "describe.skip('parser'"):
        r = edit(tmp_path, "src/parser.test.ts", "it('parses', () => {", new,
                 session=f"s-{hash(new)}")
        assert r.returncode == 2, new


def test_go_and_rust_and_junit_markers_alarm(tmp_path):
    cases = [
        ("pkg/parser_test.go", "func TestParse(t *testing.T) {",
         "func TestParse(t *testing.T) {\n\tt.Skip(\"broken\")"),
        ("src/parser/tests/basic.rs", "#[test]", "#[test]\n#[ignore]"),
        ("src/test/java/ParserTest.java", "@Test", "@Disabled\n@Test"),
    ]
    for i, (path, old, new) in enumerate(cases):
        r = edit(tmp_path, path, old, new, session=f"s{i}")
        assert r.returncode == 2, path


def test_non_test_file_never_alarms(tmp_path):
    r = edit(tmp_path, "src/parser.py",
             "def run():", "@pytest.mark.skip\ndef run():")
    assert r.returncode == 0


def test_moving_existing_skip_stays_silent(tmp_path):
    # Marker count unchanged: refactoring around an existing skip is not weakening.
    r = edit(tmp_path, "tests/test_parser.py",
             "@pytest.mark.skip\ndef test_a():", "def test_a():\n    pass\n\n@pytest.mark.skip\ndef test_b():")
    assert r.returncode == 0


def test_removing_a_skip_stays_silent(tmp_path):
    r = edit(tmp_path, "tests/test_parser.py",
             "@pytest.mark.skip\ndef test_a():", "def test_a():")
    assert r.returncode == 0


def test_ordinary_test_edit_stays_silent(tmp_path):
    r = edit(tmp_path, "tests/test_parser.py",
             "assert parse('') == []", "assert parse('') == []\nassert parse('x') == ['x']")
    assert r.returncode == 0


def test_fires_once_per_file_per_session(tmp_path):
    edit(tmp_path, "tests/test_a.py", "def test():", "@pytest.mark.skip\ndef test():")
    r = edit(tmp_path, "tests/test_a.py", "def test2():", "@pytest.mark.skip\ndef test2():")
    assert r.returncode == 0
    # ...but a different file in the same session still fires
    r = edit(tmp_path, "tests/test_b.py", "def test():", "@pytest.mark.skip\ndef test():")
    assert r.returncode == 2


def test_write_of_new_test_file_with_skip_alarms(tmp_path):
    r = run_hook(tmp_path, "Write", {
        "file_path": "tests/test_new.py",
        "content": "import pytest\n@pytest.mark.skip\ndef test_todo(): ...\n",
    })
    assert r.returncode == 2


def test_windows_backslash_test_path_alarms(tmp_path):
    # CONF1: native-Windows Edit/Write payloads carry backslash file_paths. Without
    # separator normalization the tests/ and test_*.py heuristics never fire on
    # Windows — the alarm would be silently inert on a supported platform.
    r = edit(tmp_path, r"C:\repo\tests\test_foo.py",
             "def test_x():", "@pytest.mark.skip\ndef test_x():")
    assert r.returncode == 2
    r2 = edit(tmp_path, r"src\tests\test_bar.py",
              "def test_y():", "@unittest.skip('later')\ndef test_y():", session="s2")
    assert r2.returncode == 2


def test_bash_tool_ignored(tmp_path):
    r = run_hook(tmp_path, "Bash", {"command": "echo '@pytest.mark.skip' >> tests/test_a.py"})
    assert r.returncode == 0


def test_malformed_stdin_fails_open(tmp_path):
    r = run_hook(tmp_path, "Edit", {}, raw_stdin="not json")
    assert r.returncode == 0


def test_missing_fields_fail_open(tmp_path):
    r = run_hook(tmp_path, "Edit", {"file_path": "tests/test_a.py"})
    assert r.returncode == 0


def test_path_heuristic_in_sync_with_claim_audit():
    # Both hooks must agree on what a test file is; drift would let a weakening
    # edit alarm on a file the stop-gate then ignores (or vice versa).
    import importlib.util

    def load(path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    hooks = Path(__file__).resolve().parents[1] / "claude" / "hooks"
    alarm = load(hooks / "posttool-test-weakening-alarm.py", "alarm")
    gate = load(hooks / "stop-claim-audit.py", "gate")
    assert alarm.TEST_PATH.pattern == gate.TEST_PATH.pattern
    assert alarm.TEST_PATH.flags == gate.TEST_PATH.flags
