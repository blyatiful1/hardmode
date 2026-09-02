# Unit tests for the PreToolUse memory privacy guard (real subprocess, scratch config dir).
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pretool-mem-privacy-guard.py"


def write_privacy(claude_dir, patterns):
    mdir = Path(claude_dir) / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "privacy.toml").write_text("patterns = [%s]\n" % ", ".join('"%s"' % p for p in patterns))


def run_hook(claude_dir, file_path=None, content=None, tool="Write", tool_input=None,
             raw_stdin=None, env_extra=None, cwd=None):
    if tool_input is None:
        tool_input = {}
        if file_path is not None:
            tool_input["file_path"] = str(file_path)
        if content is not None:
            tool_input["content"] = content
    payload = {"tool_name": tool, "tool_input": tool_input, "session_id": "p1"}
    if cwd:
        payload["cwd"] = str(cwd)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(claude_dir), HARDMODE_STATE_DIR=str(Path(claude_dir) / "st"))
    env.pop("CLAUDE_DIR", None)
    env.pop("CLAUDE_CODE_REMOTE_MEMORY_DIR", None)
    # point the plugin fallback at an EMPTY doctrine unless a test wants the shipped one
    env["CLAUDE_PLUGIN_ROOT"] = env.get("HARDMODE_TEST_PLUGIN_ROOT", str(Path(claude_dir) / "no-plugin"))
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(HOOK)],
                          input=raw_stdin if raw_stdin is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=env)


def corpus_file(claude_dir, name):
    return Path(claude_dir) / "memory" / name


def project_memory_file(claude_dir, name, slug="-home-user-repo"):
    return Path(claude_dir) / "projects" / slug / "memory" / name


# ---- legacy machine-wide corpus ----

def test_marker_write_into_corpus_is_blocked(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    r = run_hook(tmp_path, corpus_file(tmp_path, "leak.md"), "notes mentioning ACME-1234 internally")
    assert r.returncode == 2
    assert "MEMORY PRIVACY GUARD" in r.stderr


def test_marker_write_outside_any_corpus_is_allowed(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    outside = Path(tmp_path) / "projects" / "repoA" / "notes" / "leak.md"
    assert run_hook(tmp_path, outside, "notes mentioning ACME-1234 internally").returncode == 0
    assert run_hook(tmp_path, tmp_path / "src" / "x.py", "ACME-1234").returncode == 0


def test_clean_write_into_corpus_is_allowed(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    assert run_hook(tmp_path, corpus_file(tmp_path, "note.md"), "a clean cross-project lesson").returncode == 0


# ---- the native auto-memory tree (where MEMORY.md actually lives) ----

def test_native_project_memory_is_guarded(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    r = run_hook(tmp_path, project_memory_file(tmp_path, "MEMORY.md"), "root cause: ACME-1234 rollout")
    assert r.returncode == 2
    assert "project memory corpus" in r.stderr
    assert run_hook(tmp_path, project_memory_file(tmp_path, "topic.md"), "clean lesson").returncode == 0


def test_remote_memory_dir_env_is_honored(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    remote = tmp_path / "remote-mem"
    target = remote / "projects" / "-home-user-repo" / "memory" / "MEMORY.md"
    r = run_hook(tmp_path, target, "ACME-1234", env_extra={"CLAUDE_CODE_REMOTE_MEMORY_DIR": str(remote)})
    assert r.returncode == 2


def test_relative_memory_path_is_resolved_against_cwd(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    slug_dir = tmp_path / "projects" / "-home-user-repo"
    (slug_dir / "memory").mkdir(parents=True)
    r = run_hook(tmp_path, "memory/MEMORY.md", "ACME-1234", cwd=slug_dir)
    assert r.returncode == 2


# ---- pattern sources ----

def test_shipped_defaults_catch_secrets_without_any_operator_file(tmp_path):
    # No <config>/memory/privacy.toml at all: the plugin's doctrine/privacy.toml arms the guard.
    for secret in ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...", "token ghp_abcdef123456",
                   "key sk-ant-api03-xyz", "aws AKIAIOSFODNN7EXAMPLE"):
        r = run_hook(tmp_path, project_memory_file(tmp_path, "MEMORY.md"), secret,
                     env_extra={"CLAUDE_PLUGIN_ROOT": str(ROOT)})
        assert r.returncode == 2, secret
    r = run_hook(tmp_path, project_memory_file(tmp_path, "MEMORY.md"),
                 "the build takes 4 minutes on this box", env_extra={"CLAUDE_PLUGIN_ROOT": str(ROOT)})
    assert r.returncode == 0


def test_operator_file_wins_over_shipped_defaults(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    r = run_hook(tmp_path, corpus_file(tmp_path, "leak.md"), "token ghp_abcdef",
                 env_extra={"CLAUDE_PLUGIN_ROOT": str(ROOT)})
    assert r.returncode == 0   # the operator's list (no ghp_) is the one in force


def test_no_patterns_anywhere_fails_open_and_records_inertness(tmp_path):
    (Path(tmp_path) / "memory").mkdir(parents=True, exist_ok=True)
    r = run_hook(tmp_path, corpus_file(tmp_path, "leak.md"), "notes mentioning ACME-1234 internally")
    assert r.returncode == 0
    recs = [json.loads(ln) for ln in (tmp_path / "st" / "ledger-p1.jsonl").read_text().splitlines()]
    assert any(x["hook"] == "mem-privacy" and x["outcome"] == "inert-no-patterns" for x in recs)


def test_empty_patterns_fails_open(tmp_path):
    write_privacy(tmp_path, [])
    assert run_hook(tmp_path, corpus_file(tmp_path, "leak.md"), "ACME-1234").returncode == 0


def test_minimal_parser_works_without_tomllib(monkeypatch):
    spec = importlib.util.spec_from_file_location("mem_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setitem(sys.modules, "tomllib", None)   # `import tomllib` raises ImportError
    raw = '# comment\npatterns = [\n  "ACME-*",  # ticket ids\n  \'host.corp\',\n  # "disabled",\n]\n'
    assert mod._parse_patterns(raw) == ["ACME-*", "host.corp"]
    assert mod._parse_patterns("nothing here") == []


# ---- tool shapes ----

def test_edit_new_string_and_batch_edits_are_scanned(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    target = str(corpus_file(tmp_path, "note.md"))
    r = run_hook(tmp_path, tool="Edit", tool_input={"file_path": target, "old_string": "a",
                                                      "new_string": "see ACME-99"})
    assert r.returncode == 2
    r = run_hook(tmp_path, tool="Edit", tool_input={"file_path": target,
                                                      "edits": [{"old_string": "a", "new_string": "ACME-7"}]})
    assert r.returncode == 2
    r = run_hook(tmp_path, tool="Edit", tool_input={"file_path": target, "old_string": "a", "new_string": "clean"})
    assert r.returncode == 0


def test_other_tools_are_not_this_guards_business(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    assert run_hook(tmp_path, corpus_file(tmp_path, "leak.md"), "ACME-1234", tool="Bash").returncode == 0


def test_path_traversal_out_of_corpus_is_not_blocked(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    traversal = corpus_file(tmp_path, "../elsewhere/leak.md")
    assert run_hook(tmp_path, traversal, "notes mentioning ACME-1234 internally").returncode == 0


def test_case_insensitive_fs_variant_path_is_blocked(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    variant = Path(tmp_path) / "Memory" / "leak.md"
    r = run_hook(tmp_path, variant, "secret ACME-1234", env_extra={"HARDMODE_MEM_FS_CASE_INSENSITIVE": "1"})
    assert r.returncode == 2


@pytest.mark.skipif(os.name == "nt", reason="NTFS case-folds before the guard compares")
def test_case_sensitive_fs_variant_path_is_allowed(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    variant = Path(tmp_path) / "Memory" / "leak.md"
    r = run_hook(tmp_path, variant, "secret ACME-1234", env_extra={"HARDMODE_MEM_FS_CASE_INSENSITIVE": "0"})
    assert r.returncode == 0


def test_malformed_stdin_fails_open(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    assert run_hook(tmp_path, raw_stdin="not json").returncode == 0


def test_non_ascii_content_still_blocks_under_ascii_locale(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": str(corpus_file(tmp_path, "leak.md")),
        "content": "café notes — ACME-1234 leak — localización 日本語"}}
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(tmp_path), PYTHONIOENCODING="ascii")
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=30, env=env)
    assert r.returncode == 2, r.stderr


def test_base_honors_claude_config_dir_not_claude_dir(tmp_path):
    # CLAUDE_CONFIG_DIR is the real harness variable; CLAUDE_DIR never existed.
    base_a, base_b = tmp_path / "a", tmp_path / "b"
    write_privacy(base_a, ["ACME-*"])
    (base_b / "memory").mkdir(parents=True, exist_ok=True)
    target = corpus_file(base_a, "leak.md")
    assert run_hook(base_a, target, "mentions ACME-1234").returncode == 2
    assert run_hook(base_b, target, "mentions ACME-1234").returncode == 0
    # a stale CLAUDE_DIR must not override a set CLAUDE_CONFIG_DIR
    r = run_hook(base_a, target, "mentions ACME-1234", env_extra={"CLAUDE_DIR": str(base_b)})
    assert r.returncode == 2
