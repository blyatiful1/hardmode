# Unit tests for the PreToolUse memory privacy guard.
# Exercised as a real subprocess reading real stdin against a scratch CLAUDE_DIR.
# The guard BLOCKS (exit 2) a write into $BASE/memory/ whose pending content hits a
# privacy.toml pattern, and fails OPEN (exit 0) on every ambiguity — the destructive
# guard precedent: only ever block on a positive match of configured content.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "claude" / "hooks" / "pretool-mem-privacy-guard.py"


def write_privacy(claude_dir, patterns):
    mdir = Path(claude_dir) / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    body = "patterns = [%s]\n" % ", ".join('"%s"' % p for p in patterns)
    (mdir / "privacy.toml").write_text(body)


def run_hook(claude_dir, file_path=None, content=None, tool="Write",
             tool_input=None, raw_stdin=None):
    if tool_input is None:
        tool_input = {}
        if file_path is not None:
            tool_input["file_path"] = str(file_path)
        if content is not None:
            tool_input["content"] = content
    payload = {"tool_name": tool, "tool_input": tool_input}
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def corpus_file(claude_dir, name):
    return Path(claude_dir) / "memory" / name


# ---------------------------------------------------------------------------
def test_marker_write_into_corpus_is_blocked(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    r = run_hook(tmp_path, corpus_file(tmp_path, "leak.md"),
                 "notes mentioning ACME-1234 internally")
    assert r.returncode == 2
    assert "MEMORY PRIVACY GUARD" in r.stderr


def test_marker_write_outside_corpus_is_allowed(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    # a project-scoped memory is NOT the global corpus — not the guard's concern
    outside = Path(tmp_path) / "projects" / "repoA" / "memory" / "leak.md"
    r = run_hook(tmp_path, outside, "notes mentioning ACME-1234 internally")
    assert r.returncode == 0


def test_clean_write_into_corpus_is_allowed(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    r = run_hook(tmp_path, corpus_file(tmp_path, "note.md"),
                 "a perfectly clean cross-project lesson")
    assert r.returncode == 0


def test_no_privacy_toml_fails_open(tmp_path):
    # no privacy.toml at all: can't honestly block => allow, even with a marker
    (Path(tmp_path) / "memory").mkdir(parents=True, exist_ok=True)
    r = run_hook(tmp_path, corpus_file(tmp_path, "leak.md"),
                 "notes mentioning ACME-1234 internally")
    assert r.returncode == 0


def test_empty_patterns_fails_open(tmp_path):
    write_privacy(tmp_path, [])
    r = run_hook(tmp_path, corpus_file(tmp_path, "leak.md"),
                 "notes mentioning ACME-1234 internally")
    assert r.returncode == 0


def test_path_traversal_out_of_corpus_is_not_blocked(tmp_path):
    # $BASE/memory/../elsewhere resolves OUT of the corpus via realpath, so it is
    # out of blocked scope (documented: the guard scopes by resolved real path).
    write_privacy(tmp_path, ["ACME-*"])
    traversal = corpus_file(tmp_path, "../elsewhere/leak.md")
    r = run_hook(tmp_path, traversal, "notes mentioning ACME-1234 internally")
    assert r.returncode == 0


def test_case_insensitive_fs_variant_path_is_blocked(tmp_path):
    # On a case-insensitive fs (macOS APFS/HFS+), $BASE/Memory/ IS $BASE/memory/, so a
    # capitalized target must not slip a marker past the guard. Forced via the env seam
    # since the CI fs is case-sensitive.
    write_privacy(tmp_path, ["ACME-*"])
    variant = Path(tmp_path) / "Memory" / "leak.md"     # capital M
    env = dict(os.environ, CLAUDE_DIR=str(tmp_path), FABLE_MEM_FS_CASE_INSENSITIVE="1")
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": str(variant), "content": "secret ACME-1234"}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 2
    assert "MEMORY PRIVACY GUARD" in r.stderr


def test_case_sensitive_fs_variant_path_is_allowed(tmp_path):
    # With case-sensitivity forced off, $BASE/Memory/ is a genuinely distinct dir and
    # must NOT be blocked (no false-block of a real sibling on Linux).
    write_privacy(tmp_path, ["ACME-*"])
    variant = Path(tmp_path) / "Memory" / "leak.md"
    env = dict(os.environ, CLAUDE_DIR=str(tmp_path), FABLE_MEM_FS_CASE_INSENSITIVE="0")
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": str(variant), "content": "secret ACME-1234"}}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0


def test_malformed_stdin_fails_open(tmp_path):
    write_privacy(tmp_path, ["ACME-*"])
    r = run_hook(tmp_path, raw_stdin="not json")
    assert r.returncode == 0


def test_base_honors_claude_dir(tmp_path):
    # privacy.toml + the blocking decision are read from CLAUDE_DIR. The SAME
    # payload blocks under a base that has the config, and is allowed under a base
    # that does not (target no longer under that base's corpus / no patterns).
    base_a = tmp_path / "a"
    base_b = tmp_path / "b"
    write_privacy(base_a, ["ACME-*"])
    (base_b / "memory").mkdir(parents=True, exist_ok=True)
    target = corpus_file(base_a, "leak.md")

    blocked = run_hook(base_a, target, "mentions ACME-1234")
    assert blocked.returncode == 2

    allowed = run_hook(base_b, target, "mentions ACME-1234")
    assert allowed.returncode == 0  # target not under base_b's corpus => allowed
