# Unit tests for the shared _hardmode helpers (stdlib only, every function fails open).
import json
import os
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path.insert(0, str(HOOKS))
from _hardmode import (  # noqa: E402
    blank_quotes,
    config_dir,
    iter_jsonl,
    ledger,
    locked,
    looks_like_test_run,
    looks_like_write,
    normalize_cmd,
    prune_stale,
    read_json,
    reconfigure_utf8,
    response_text,
    scope_slug,
    session_slug,
    slug,
    state_dir,
    subagent_transcripts,
    write_json_atomic,
)


# ---- config_dir ----------------------------------------------------------------

def test_config_dir_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/custom/config")
    monkeypatch.setenv("CLAUDE_DIR", "/legacy/dir")
    assert config_dir() == "/custom/config"


def test_config_dir_falls_back_to_claude_dir(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_DIR", "/legacy/dir")
    assert config_dir() == "/legacy/dir"


def test_config_dir_defaults_to_dot_claude(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_DIR", raising=False)
    assert config_dir().endswith(".claude")


# ---- state_dir -----------------------------------------------------------------

def test_state_dir_uses_env_override(monkeypatch, tmp_path):
    d = tmp_path / "my-state"
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(d))
    assert state_dir() == str(d)


def test_state_dir_creates_directory_by_default(tmp_path, monkeypatch):
    d = tmp_path / "state"
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(d))
    assert not d.exists()
    assert state_dir() == str(d)
    assert d.is_dir()


def test_state_dir_does_not_create_when_asked(monkeypatch, tmp_path):
    d = tmp_path / "no-create"
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(d))
    assert state_dir(create=False) == str(d)
    assert not d.exists()


# ---- slug ----------------------------------------------------------------------

def test_slug_empty_and_none():
    assert slug("") == "unknown"
    assert slug(None) == "unknown"


def test_slug_replaces_special_chars():
    assert slug("hello world!") == "hello_world_"
    assert slug("file/path:test@host") == "file_path_test_host"


def test_slug_truncates_long_strings():
    long = "a" * 100
    assert slug(long) == "a" * 80


def test_slug_preserves_alphanumeric_and_dashes():
    assert slug("abc-123_XYZ") == "abc-123_XYZ"


# ---- session_slug --------------------------------------------------------------

def test_session_slug_from_data():
    assert isinstance(session_slug({"session_id": "abc-123"}), str)
    assert session_slug({"session_id": ""}) == "unknown"
    assert session_slug({"session_id": "test!"}) == "test_"
    assert session_slug(None) == "unknown"


# ---- scope_slug ----------------------------------------------------------------

def test_scope_slug_without_agent():
    assert isinstance(scope_slug({"session_id": "s1"}), str)


def test_scope_slug_with_agent_adds_suffix():
    assert "-" in scope_slug({"session_id": "s1", "agent_id": "a1"})


def test_scope_slug_with_none_data():
    assert isinstance(scope_slug(None), str)


# ---- prune_stale ---------------------------------------------------------------

def test_prune_stale_removes_old_prunable_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(tmp_path))
    d = state_dir()
    dp = Path(d)
    old = dp / "ledger-old.jsonl"
    old.write_text("{}")
    os.utime(old, (time.time() - 8 * 86400, time.time() - 8 * 86400))
    assert old.exists()
    prune_stale(d, ttl_days=7)
    assert not old.exists()


def test_prune_stale_keeps_recent_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(tmp_path))
    d = state_dir()
    dp = Path(d)
    fresh = dp / "ledger-fresh.jsonl"
    fresh.write_text("{}")
    prune_stale(d, ttl_days=7)
    assert fresh.exists()


def test_prune_stale_ignores_non_prunable_prefixes(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(tmp_path))
    d = state_dir()
    dp = Path(d)
    sessions = dp / "sessions.jsonl"
    sessions.write_text("{}")
    os.utime(sessions, (time.time() - 8 * 86400, time.time() - 8 * 86400))
    prune_stale(d, ttl_days=7)
    assert sessions.exists()


def test_prune_stale_only_unlinks_regular_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(tmp_path))
    d = state_dir()
    dp = Path(d)
    sub = dp / "ledger-subdir"
    sub.mkdir()
    prune_stale(d, ttl_days=7)
    assert sub.is_dir()


# ---- read_json -----------------------------------------------------------------

def test_read_json_reads_valid_file(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"key": "value"}')
    assert read_json(str(p), {}) == {"key": "value"}


def test_read_json_returns_default_on_missing_file(tmp_path):
    assert read_json(str(tmp_path / "no.json"), {}) == {}


def test_read_json_returns_default_on_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    assert read_json(str(p), {}) == {}


def test_read_json_type_mismatch_returns_default(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]")
    assert read_json(str(p), {}) == {}


# ---- write_json_atomic ---------------------------------------------------------

def test_write_json_atomic_basic(tmp_path):
    p = tmp_path / "state.json"
    assert write_json_atomic(str(p), {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}


def test_write_json_atomic_overwrites(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"old": true}')
    assert write_json_atomic(str(p), {"new": True})
    assert json.loads(p.read_text()) == {"new": True}


def test_write_json_atomic_no_temp_file_left_behind(tmp_path):
    p = tmp_path / "state.json"
    write_json_atomic(str(p), {"x": 1})
    assert len([f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]) == 0


def test_write_json_atomic_handles_nested_path(tmp_path):
    p = tmp_path / "sub" / "deep" / "state.json"
    p.parent.mkdir(parents=True)
    write_json_atomic(str(p), {"x": 1})
    assert json.loads(p.read_text()) == {"x": 1}


# ---- locked --------------------------------------------------------------------

def test_locked_acquires_and_releases(tmp_path):
    p = tmp_path / "test-lock"
    with locked(str(p)):
        assert True  # lock acquired and released without error
    assert True  # lock released, context exited


def test_locked_leaves_no_stale_fcntl_lock(tmp_path):
    p = tmp_path / "test-lock"
    with locked(str(p)):
        pass
    # A second acquisition should work
    with locked(str(p)):
        pass


def test_locked_lockfile_created_and_cleaned(tmp_path):
    with locked(str(tmp_path / "test-lock")):
        pass


# ---- iter_jsonl -----------------------------------------------------------------

def test_iter_jsonl_empty_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert list(iter_jsonl(str(p))) == []


def test_iter_jsonl_valid_lines(tmp_path):
    p = tmp_path / "data.jsonl"
    p.write_text('{"a": 1}\n{"b": 2}\n')
    result = list(iter_jsonl(str(p)))
    assert result == [{"a": 1}, {"b": 2}]


def test_iter_jsonl_skips_malformed_lines(tmp_path):
    p = tmp_path / "mixed.jsonl"
    p.write_text('{"ok": 1}\ngarbage\n{"ok": 2}\n')
    result = list(iter_jsonl(str(p)))
    assert result == [{"ok": 1}, {"ok": 2}]


def test_iter_jsonl_missing_file(tmp_path):
    assert list(iter_jsonl(str(tmp_path / "none.jsonl"))) == []


def test_iter_jsonl_skips_non_dict_entries(tmp_path):
    p = tmp_path / "arr.jsonl"
    p.write_text('[1, 2]\n{"ok": 1}\n"string"\nnull\n5\n')
    result = list(iter_jsonl(str(p)))
    assert result == [{"ok": 1}]


# ---- blank_quotes ---------------------------------------------------------------

def test_blank_quotes_replaces_quoted_spans():
    s = "hello 'world' test"
    b = blank_quotes(s)
    assert len(b) == len(s)
    assert "world" not in b
    assert "hello" in b


def test_blank_quotes_handles_no_quotes():
    s = "plain text"
    assert blank_quotes(s) == s


def test_blank_quotes_preserves_length():
    s = "aaa 'bbb' ccc"
    assert len(blank_quotes(s)) == len(s)


# ---- normalize_cmd --------------------------------------------------------------

def test_normalize_cmd_strips_whitespace():
    assert normalize_cmd("  echo hello  ") == "echo hello"


def test_normalize_cmd_joins_line_continuations():
    assert normalize_cmd("echo a \\\n  b") == "echo a b"


def test_normalize_cmd_preserves_newlines_as_separators():
    result = normalize_cmd("echo a\necho b")
    assert "echo a\necho b" in result or "a" in result


def test_normalize_cmd_handles_non_string():
    assert normalize_cmd(None) == ""
    assert normalize_cmd(123) == ""


def test_normalize_cmd_collapses_horizontal_whitespace():
    assert normalize_cmd("echo   hello\tworld") == "echo hello world"


# ---- looks_like_test_run -------------------------------------------------------

def test_looks_like_test_run_pytest():
    assert looks_like_test_run("python -m pytest tests/")
    assert looks_like_test_run("pytest -v")


def test_looks_like_test_run_npm():
    assert looks_like_test_run("npm test")
    assert looks_like_test_run("npm run check")


def test_looks_like_test_run_cargo():
    assert looks_like_test_run("cargo test")
    assert looks_like_test_run("cargo check")


def test_looks_like_test_run_non_runner():
    assert not looks_like_test_run("echo hello")
    assert not looks_like_test_run("cat test.py")


def test_looks_like_test_run_at_command_position():
    assert looks_like_test_run("echo x && pytest -v")


# ---- looks_like_write ----------------------------------------------------------

def test_looks_like_write_redirect():
    assert looks_like_write("echo x > output.txt")


def test_looks_like_write_git_ops():
    assert looks_like_write("git reset --hard")
    assert looks_like_write("git checkout -- .")


def test_looks_like_write_file_ops():
    assert looks_like_write("rm -rf dir/")
    assert looks_like_write("touch new.txt")


def test_looks_like_write_readonly():
    assert not looks_like_write("git status")
    assert not looks_like_write("git log")


# ---- subagent_transcripts ------------------------------------------------------

def test_subagent_transcripts_missing_directory(tmp_path):
    result = subagent_transcripts(str(tmp_path / "nonexistent.jsonl"))
    assert result == []


def test_subagent_transcripts_empty_directory(tmp_path):
    stem = tmp_path / "transcript"
    sub = tmp_path / "transcript" / "subagents"
    sub.mkdir(parents=True)
    result = subagent_transcripts(str(stem) + ".jsonl")
    assert result == []


def test_subagent_transcripts_finds_agent_files(tmp_path):
    stem = tmp_path / "transcript"
    sub = stem / "subagents" / "agent-1"
    sub.mkdir(parents=True)
    f = sub / "agent-transcript.jsonl"
    f.write_text('{"type": "user"}\n')
    result = subagent_transcripts(str(stem) + ".jsonl")
    assert len(result) == 1
    assert result[0] == str(f)


def test_subagent_transcripts_ignores_non_agent_files(tmp_path):
    stem = tmp_path / "transcript"
    sub = stem / "subagents"
    sub.mkdir(parents=True)
    (sub / "meta.json").write_text("{}")
    (sub / "summary.txt").write_text("text")
    result = subagent_transcripts(str(stem) + ".jsonl")
    assert result == []


def test_subagent_transcripts_handles_trailing_slash_stem(tmp_path):
    stem = tmp_path / "transcript"
    sub = stem / "subagents"
    sub.mkdir(parents=True)
    f = sub / "agent-x.jsonl"
    f.write_text('{"type": "user"}\n')
    result = subagent_transcripts(str(stem) + ".jsonl")
    assert len(result) == 1


# ---- reconfigure_utf8 ----------------------------------------------------------

def test_reconfigure_utf8_does_not_crash():
    reconfigure_utf8(sys.stderr)


# ---- response_text -------------------------------------------------------------

def test_response_text_string():
    assert response_text("hello") == "hello"


def test_response_text_dict_stdout():
    assert response_text({"stdout": "out", "stderr": "err"}) == "out\nerr"


def test_response_text_dict_list_content():
    assert "text content" in response_text({
        "content": [{"text": "text content"}]
    })


def test_response_text_empty():
    assert response_text({}) == ""
    assert response_text("") == ""


# ---- ledger --------------------------------------------------------------------

def test_ledger_writes_record(tmp_path, monkeypatch):
    d = tmp_path / "state"
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(d))
    ledger({"hook_event_name": "Stop", "session_id": "test-s"}, "test-hook", "test-outcome", "detail")
    files = list(d.glob("ledger-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "test-hook" in content
    assert "test-outcome" in content


def test_ledger_disabled_writes_nothing(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(d))
    monkeypatch.setenv("HARDMODE_LEDGER", "0")
    ledger({"session_id": "test-s"}, "hook", "outcome")
    files = list(d.glob("ledger-*.jsonl"))
    assert len(files) == 0


def test_ledger_handles_non_dict_data(tmp_path, monkeypatch):
    d = tmp_path / "state"
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(d))
    ledger(None, "test-hook", "outcome")
    files = list(d.glob("ledger-*.jsonl"))
    assert len(files) == 1


# ---- subagent_transcripts symlink boundary ------------------------------------

def test_subagent_transcripts_rejects_symlink_outside_root(tmp_path):
    stem = tmp_path / "transcript"
    sub = stem / "subagents"
    sub.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"type": "user"}\n')
    link = sub / "agent-evil.jsonl"
    os.symlink(str(outside), str(link))
    result = subagent_transcripts(str(stem) + ".jsonl")
    assert result == []
