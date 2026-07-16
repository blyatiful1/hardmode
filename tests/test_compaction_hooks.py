# Unit tests for the PreCompact save-task hook and SessionStart(compact) recovery hook.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "claude" / "hooks"
SAVE = HOOKS / "precompact-save-task.py"
RECOVER = HOOKS / "sessionstart-compact-recovery.py"


def run(hook, payload, state_dir, raw_stdin=None):
    env = dict(os.environ, FABLE_STATE_DIR=str(state_dir))
    return subprocess.run(
        [sys.executable, str(hook)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def transcript(tmp_path, entries):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return p


def user_entry(content, is_meta=False):
    e = {"type": "user", "message": {"content": content}}
    if is_meta:
        e["isMeta"] = True
    return e


def saved(state_dir, session="s1"):
    return Path(state_dir) / f"original-task-{session}.txt"


def test_saves_first_user_message_verbatim(tmp_path):
    t = transcript(tmp_path, [
        {"type": "assistant", "message": {"content": []}},
        user_entry("Fix the parser so empty logs don't crash the CLI."),
        user_entry("also update the docs"),
    ])
    r = run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    assert r.returncode == 0
    assert saved(tmp_path).read_text() == "Fix the parser so empty logs don't crash the CLI."


def test_block_list_content_and_meta_skipped(tmp_path):
    t = transcript(tmp_path, [
        user_entry("harness bookkeeping", is_meta=True),
        user_entry([{"type": "text", "text": "Real request here"},
                    {"type": "tool_result", "content": "noise"}]),
    ])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    assert saved(tmp_path).read_text() == "Real request here"


def test_system_reminders_stripped(tmp_path):
    t = transcript(tmp_path, [
        user_entry("<system-reminder>injected</system-reminder>Do the thing"),
    ])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    assert saved(tmp_path).read_text() == "Do the thing"


def test_long_task_truncated(tmp_path):
    t = transcript(tmp_path, [user_entry("x" * 10000)])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    text = saved(tmp_path).read_text()
    assert len(text) < 5000 and "truncated" in text


def test_missing_transcript_fails_open(tmp_path):
    r = run(SAVE, {"session_id": "s1", "transcript_path": str(tmp_path / "nope")}, tmp_path)
    assert r.returncode == 0
    assert not saved(tmp_path).exists()


def test_recovery_injects_protocol_task_and_git_state(tmp_path):
    saved(tmp_path).write_text("Fix the parser.")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "dirty.txt").write_text("x")
    r = run(RECOVER, {"session_id": "s1", "cwd": str(repo)}, tmp_path)
    assert r.returncode == 0
    assert "CONTEXT JUST COMPACTED" in r.stdout
    assert "Fix the parser." in r.stdout
    assert "dirty.txt" in r.stdout


def test_recovery_without_saved_task_still_prints_protocol(tmp_path):
    r = run(RECOVER, {"session_id": "s1", "cwd": str(tmp_path)}, tmp_path)
    assert r.returncode == 0
    assert "CONTEXT JUST COMPACTED" in r.stdout
    assert "original request" not in r.stdout


def test_recovery_truncates_huge_git_status(tmp_path):
    # A 500-file dirty tree must not flood the fresh post-compaction context.
    saved(tmp_path).write_text("Fix the parser.")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for i in range(60):
        (repo / f"dirty-{i:03}.txt").write_text("x")
    r = run(RECOVER, {"session_id": "s1", "cwd": str(repo)}, tmp_path)
    assert r.returncode == 0
    status_lines = [ln for ln in r.stdout.splitlines() if "dirty-" in ln]
    assert 0 < len(status_lines) <= 30


def test_recovery_malformed_stdin_fails_open(tmp_path):
    r = run(RECOVER, {}, tmp_path, raw_stdin="not json")
    assert r.returncode == 0
    assert "CONTEXT JUST COMPACTED" in r.stdout


def test_non_ascii_request_survives_the_save_recover_round_trip(tmp_path):
    # The user's request and the transcript are UTF-8; under a legacy-locale
    # Python (cp1252 on Windows <=3.14) an emoji used to crash the save (fail-open
    # -> no state file) and the recovery print — the kit's flagship compaction
    # recovery silently inert on real sessions. PYTHONIOENCODING simulates the
    # worst-case console; the transcript/state files exercise the open() paths.
    msg = "Baue das Widget \U0001f355 mit Umlauten: äöüß"
    t = tmp_path / "transcript.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": msg}},
                            ensure_ascii=False), encoding="utf-8")
    env_io = dict(os.environ, FABLE_STATE_DIR=str(tmp_path), PYTHONIOENCODING="cp1252")
    r = subprocess.run([sys.executable, str(SAVE)],
                       input=json.dumps({"session_id": "s1", "transcript_path": str(t)},
                                        ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=30, env=env_io)
    assert r.returncode == 0
    assert saved(tmp_path).read_text(encoding="utf-8") == msg

    r2 = subprocess.run([sys.executable, str(RECOVER)],
                        input=json.dumps({"session_id": "s1", "cwd": str(tmp_path)}).encode("utf-8"),
                        capture_output=True, timeout=30, env=env_io)
    assert r2.returncode == 0
    out = r2.stdout.decode("utf-8", errors="replace")
    assert "CONTEXT JUST COMPACTED" in out
    assert msg in out
