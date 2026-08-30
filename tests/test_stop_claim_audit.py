# Unit tests for the Stop-hook claim-audit gate.
# Run with: pytest tests/ -q
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "stop-claim-audit.py"


def text_entry(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def tool_entry(name, **input_):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": input_}]}}


def run_hook(tmp_path, entries, last_message=None, stop_hook_active=False, raw_stdin=None):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in entries))
    payload = {"transcript_path": str(transcript), "stop_hook_active": stop_hook_active}
    if last_message is not None:
        payload["last_assistant_message"] = last_message
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30,
    )


def test_blocks_claim_after_edit(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Edit", file_path="x.py")],
                 last_message="All done — tests pass and the fix is verified.")
    assert r.returncode == 2
    assert "CLAIM AUDIT GATE" in r.stderr


def test_no_block_without_modification(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Read", file_path="x.py")],
                 last_message="Done — everything is verified.")
    assert r.returncode == 0


def test_no_block_without_claim(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Write", file_path="x.py")],
                 last_message="I refactored the parser; next I plan to add tests.")
    assert r.returncode == 0


def test_fires_only_once(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Edit", file_path="x.py")],
                 last_message="Done and verified.", stop_hook_active=True)
    assert r.returncode == 0


def test_negated_claims_do_not_block(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Edit", file_path="x.py")],
                 last_message="The migration is not done yet; two parts remain to be fixed.")
    assert r.returncode == 0


def test_bash_file_write_counts_as_modification(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Bash", command="echo hello > config.yaml")],
                 last_message="Config fixed, all checks pass.")
    assert r.returncode == 2


def test_bash_sed_in_place_counts(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Bash", command="sed -i 's/a/b/' src/main.py")],
                 last_message="Renamed everywhere — done.")
    assert r.returncode == 2


def test_readonly_bash_does_not_count(tmp_path):
    r = run_hook(tmp_path, [
        tool_entry("Bash", command="grep -rn 'foo' src/ | head -20"),
        tool_entry("Bash", command="pytest -q > /dev/null 2>&1"),
    ], last_message="Analysis complete: the bug is in parser.py (verified by reading the code).")
    assert r.returncode == 0


def test_transcript_fallback_when_no_payload_field(tmp_path):
    r = run_hook(tmp_path, [
        tool_entry("Edit", file_path="x.py"),
        text_entry("Everything is implemented and all tests pass."),
    ])
    assert r.returncode == 2


def test_malformed_stdin_fails_open(tmp_path):
    r = run_hook(tmp_path, [], raw_stdin="this is not json")
    assert r.returncode == 0


def test_missing_transcript_fails_open(tmp_path):
    payload = {"transcript_path": str(tmp_path / "nope.jsonl"),
               "last_assistant_message": "Done and verified."}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0


def test_string_content_does_not_crash(tmp_path):
    entries = [
        {"type": "assistant", "message": {"content": "plain string content"}},
        tool_entry("Edit", file_path="x.py"),
    ]
    r = run_hook(tmp_path, entries, last_message="Fixed and verified.")
    assert r.returncode == 2


def test_test_file_edit_adds_weakening_audit(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Edit", file_path="tests/test_parser.py")],
                 last_message="All tests pass now — done.")
    assert r.returncode == 2
    assert "weakened" in r.stderr


def test_windows_backslash_test_edit_adds_weakening_audit(tmp_path):
    # CONF1: on native Windows the Edit payload's file_path uses backslashes; the
    # gate must still recognize it as a test file and attach the weakening addendum.
    r = run_hook(tmp_path, [tool_entry("Edit", file_path=r"C:\repo\tests\test_parser.py")],
                 last_message="All tests pass now — done.")
    assert r.returncode == 2
    assert "weakened" in r.stderr


def test_non_test_edit_has_no_weakening_audit(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Edit", file_path="src/parser.py")],
                 last_message="All tests pass now — done.")
    assert r.returncode == 2
    assert "weakened" not in r.stderr


def test_spec_suffix_counts_as_test_file(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Write", file_path="src/auth.spec.ts")],
                 last_message="Implemented and verified.")
    assert r.returncode == 2
    assert "weakened" in r.stderr


def test_bash_write_to_test_file_adds_weakening_audit(tmp_path):
    # v1.3 known limit, closed in v1.4: sed/redirect writes to test files used
    # to bypass the weakening addendum.
    r = run_hook(tmp_path, [tool_entry("Bash", command="sed -i 's/assert x == 2/assert True/' tests/test_math.py")],
                 last_message="All tests pass now — done.")
    assert r.returncode == 2
    assert "weakened" in r.stderr


def test_bash_redirect_into_test_file_adds_weakening_audit(tmp_path):
    r = run_hook(tmp_path, [tool_entry("Bash", command="echo 'def test_x(): pass' > src/foo_test.go")],
                 last_message="Implemented and verified.")
    assert r.returncode == 2
    assert "weakened" in r.stderr


def test_running_tests_with_log_redirect_is_not_a_test_edit(tmp_path):
    # `pytest tests/ > out.log` writes a log, not a test — gate fires (file was
    # written) but the weakening addendum must not.
    r = run_hook(tmp_path, [tool_entry("Bash", command="pytest tests/ -q > out.log")],
                 last_message="All tests pass — done.")
    assert r.returncode == 2
    assert "weakened" not in r.stderr


def test_garbage_transcript_lines_skipped(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('not json\n[1,2,3]\n' + json.dumps(tool_entry("Edit", file_path="x")))
    payload = {"transcript_path": str(transcript), "last_assistant_message": "Done, verified."}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2


def test_not_all_tests_pass_is_negated(tmp_path):
    # "Not all tests pass yet" contains the positive substring "all tests pass" —
    # the suite-claim forms need their own negation handling or honest in-progress
    # reports false-block after any edit.
    for msg in ("Not all tests pass yet — two failures remain.",
                "No checks are green so far; still debugging.",
                "None of the tests pass on Windows yet."):
        r = run_hook(tmp_path, [tool_entry("Edit", file_path="x.py")], last_message=msg)
        assert r.returncode == 0, msg


def test_positive_suite_claims_still_block(tmp_path):
    # The negation extension must not swallow genuine claims.
    for msg in ("All tests pass.", "Tests are green now.", "All checks pass, done."):
        r = run_hook(tmp_path, [tool_entry("Edit", file_path="x.py")], last_message=msg)
        assert r.returncode == 2, msg


def test_powershell_file_write_counts_as_modification(tmp_path):
    # Native-Windows sessions write files through the PowerShell tool; the Windows
    # snippets wire the gate's transcript scan to see those tool_use blocks.
    r = run_hook(tmp_path, [tool_entry("PowerShell", command="Set-Content -Path config.yaml -Value 'x'")],
                 last_message="Config fixed, all checks pass.")
    assert r.returncode == 2
    r = run_hook(tmp_path, [tool_entry("PowerShell", command='"y" | Out-File data.txt')],
                 last_message="Done and verified.")
    assert r.returncode == 2


def test_powershell_null_redirect_is_not_a_write(tmp_path):
    r = run_hook(tmp_path, [tool_entry("PowerShell", command="Get-Process > $null")],
                 last_message="Done and verified.")
    assert r.returncode == 0


def test_non_ascii_transcript_does_not_disable_the_gate(tmp_path):
    # Transcripts are UTF-8; on a cp1252-default Python an emoji (whose UTF-8 bytes
    # include codepoints undefined in cp1252) used to crash the read and fail the
    # gate OPEN — the flagship hook silently inert exactly on real sessions.
    import os
    transcript = tmp_path / "transcript.jsonl"
    entries = [text_entry("Working on the parser \U0001f355 with umlauts: äöü"),
               tool_entry("Edit", file_path="x.py")]
    transcript.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries),
                          encoding="utf-8")
    payload = {"transcript_path": str(transcript), "stop_hook_active": False,
               "last_assistant_message": "Fertig \U0001f389 — all tests pass."}
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=30, env=env)
    assert r.returncode == 2
