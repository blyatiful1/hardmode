# Unit tests for the PreCompact save hook and the SessionStart(compact) recovery hook.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
SAVE = HOOKS / "precompact-save-task.py"
RECOVER = HOOKS / "sessionstart-compact-recovery.py"


def run(hook, payload, state_dir, raw_stdin=None):
    env = dict(os.environ, HARDMODE_STATE_DIR=str(state_dir))
    return subprocess.run(
        [sys.executable, str(hook)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def transcript(tmp_path, entries):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return p


def user_entry(content, is_meta=False, compact_summary=False):
    e = {"type": "user", "message": {"content": content}}
    if is_meta:
        e["isMeta"] = True
    if compact_summary:
        e["isCompactSummary"] = True
    return e


def saved(state_dir, session="s1"):
    return Path(state_dir) / f"original-task-{session}.txt"


HERMETIC_GIT = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                    GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")


def git_repo(path, dirty_name="dirty.txt"):
    path.mkdir()
    g = lambda *a: subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=path, check=True,  # noqa: E731
                                  capture_output=True, env=HERMETIC_GIT)
    g("init", "-q", "-b", "main")
    (path / "a.txt").write_text("a")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    if dirty_name:
        (path / dirty_name).write_text("x")
    return path


# ---- PreCompact ----

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
    t = transcript(tmp_path, [user_entry("<system-reminder>injected</system-reminder>Do the thing")])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    assert saved(tmp_path).read_text() == "Do the thing"


def test_long_task_truncated(tmp_path):
    t = transcript(tmp_path, [user_entry("x" * 10000)])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    text = saved(tmp_path).read_text()
    assert len(text) < 5000 and "truncated" in text


def test_later_user_turns_are_saved_newest_last(tmp_path):
    # A later correction that reverses the scope must survive compaction too.
    t = transcript(tmp_path, [
        user_entry("Add a --json flag to the CLI."),
        user_entry("CORRECTION: do NOT touch the CLI. Migrate the parser instead."),
        user_entry("Stop hook feedback: ...", is_meta=True),
        user_entry("And add an acceptance test."),
        user_entry("previous summary", compact_summary=True),
    ])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    assert saved(tmp_path).read_text() == "Add a --json flag to the CLI."
    turns = (tmp_path / "compact-turns-s1.txt").read_text()
    assert "CORRECTION: do NOT touch the CLI" in turns
    assert "acceptance test" in turns
    assert "Stop hook feedback" not in turns and "previous summary" not in turns
    assert turns.index("CORRECTION") < turns.index("acceptance test")


def test_many_later_turns_keep_the_newest_and_count_the_omitted(tmp_path):
    entries = [user_entry("original")] + [user_entry(f"turn {i}") for i in range(2, 12)]
    t = transcript(tmp_path, entries)
    run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    turns = (tmp_path / "compact-turns-s1.txt").read_text()
    assert "turn 11" in turns and "turn 7" in turns
    assert "turn 2" not in turns
    assert "intermediate user turn(s) omitted" in turns


def test_git_snapshot_is_taken_at_compaction_time(tmp_path):
    repo = git_repo(tmp_path / "repo")
    t = transcript(tmp_path, [user_entry("do it")])
    r = run(SAVE, {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo),
                   "trigger": "auto"}, tmp_path)
    assert r.returncode == 0
    snap = (tmp_path / "compact-snapshot-s1.txt").read_text()
    assert "trigger: auto" in snap and "branch: main" in snap and "HEAD: " in snap
    assert "dirty.txt" in snap


def test_precompact_prints_summarizer_instructions(tmp_path):
    # On this build a PreCompact hook's stdout becomes the summarizer's custom
    # instructions — the preservation rule is TOLD to the summarizer deterministically.
    t = transcript(tmp_path, [user_entry("do it")])
    r = run(SAVE, {"session_id": "s1", "transcript_path": str(t)}, tmp_path)
    assert "preserve VERBATIM" in r.stdout and "original" in r.stdout.lower()


def test_missing_transcript_fails_open(tmp_path):
    r = run(SAVE, {"session_id": "s1", "transcript_path": str(tmp_path / "nope")}, tmp_path)
    assert r.returncode == 0
    assert not saved(tmp_path).exists()


# ---- SessionStart(compact) ----

def test_recovery_injects_protocol_task_and_git_state(tmp_path):
    saved(tmp_path).write_text("Fix the parser.")
    repo = git_repo(tmp_path / "repo")
    r = run(RECOVER, {"session_id": "s1", "cwd": str(repo)}, tmp_path)
    assert r.returncode == 0
    assert "CONTEXT JUST COMPACTED" in r.stdout
    assert "Fix the parser." in r.stdout
    assert "dirty.txt" in r.stdout


def test_recovery_injects_later_turns_and_snapshot_and_warns_on_moved_head(tmp_path):
    repo = git_repo(tmp_path / "repo")
    t = transcript(tmp_path, [user_entry("original ask"), user_entry("later correction")])
    run(SAVE, {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo),
               "trigger": "manual"}, tmp_path)
    # HEAD moves between compaction and recovery (a commit happened)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "wip"], cwd=repo, check=True, capture_output=True)
    r = run(RECOVER, {"session_id": "s1", "cwd": str(repo)}, tmp_path)
    assert "later correction" in r.stdout
    assert "AT compacktion time".lower() not in r.stdout.lower()  # typo guard
    assert "git state AT compaction time" in r.stdout and "trigger: manual" in r.stdout
    assert "HEAD moved since the pre-compaction snapshot" in r.stdout


def test_recovery_without_saved_task_still_prints_protocol(tmp_path):
    r = run(RECOVER, {"session_id": "s1", "cwd": str(tmp_path)}, tmp_path)
    assert r.returncode == 0
    assert "CONTEXT JUST COMPACTED" in r.stdout
    assert "original request" not in r.stdout


def test_recovery_truncates_huge_git_status(tmp_path):
    saved(tmp_path).write_text("Fix the parser.")
    repo = git_repo(tmp_path / "repo", dirty_name=None)
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
    msg = "Baue das Widget \U0001f355 mit Umlauten: äöüß"
    t = tmp_path / "transcript.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": msg}}, ensure_ascii=False),
                 encoding="utf-8")
    env_io = dict(os.environ, HARDMODE_STATE_DIR=str(tmp_path), PYTHONIOENCODING="cp1252")
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
    assert "CONTEXT JUST COMPACTED" in out and msg in out


def test_original_task_is_write_once_and_later_turns_are_rewritten(tmp_path):
    t1 = transcript(tmp_path, [user_entry("First real task"), user_entry("scope change: also X"), user_entry("and rename Y")])
    run(SAVE, {"session_id": "w1", "transcript_path": str(t1)}, tmp_path)
    assert saved(tmp_path, "w1").read_text() == "First real task"
    turns = tmp_path / "compact-turns-w1.txt"
    assert "scope change: also X" in turns.read_text() and "and rename Y" in turns.read_text()
    # second compaction: the transcript now starts with a compact summary and has fewer
    # later turns — the original task must survive and the stale turn list must go
    t2 = transcript(tmp_path, [user_entry("summary of everything", compact_summary=True),
                               user_entry("A different-looking first message"), user_entry("scope change: also X")])
    run(SAVE, {"session_id": "w1", "transcript_path": str(t2)}, tmp_path)
    assert saved(tmp_path, "w1").read_text() == "First real task"
    assert "and rename Y" not in turns.read_text()
    t3 = transcript(tmp_path, [user_entry("Only one message")])
    run(SAVE, {"session_id": "w1", "transcript_path": str(t3)}, tmp_path)
    assert saved(tmp_path, "w1").read_text() == "First real task"
    assert not turns.exists() or "scope change" not in turns.read_text()
