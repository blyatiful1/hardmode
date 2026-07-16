# Unit tests for the SessionEnd memory-journal hook.
# Exercised as a real subprocess reading real stdin against a scratch CLAUDE_DIR,
# so the journal + index side effects are proven to land under the scratch dir,
# never $HOME.
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "claude" / "hooks" / "sessionend-mem-journal.py"
MEM = ROOT / "claude" / "cli" / "mem.py"


def run_hook(claude_dir, cwd=None, reason="clear", session="s1", raw_stdin=None):
    payload = {"session_id": session, "cwd": str(cwd or ROOT),
               "reason": reason, "hook_event_name": "SessionEnd"}
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def journal_path(claude_dir):
    return Path(claude_dir) / "memory" / "journal.ndjson"


def read_lines(path):
    return [ln for ln in Path(path).read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
def test_writes_one_ndjson_line_under_tmp_claude_dir(tmp_path):
    # cwd = this git repo, so branch + dirty_count are computed.
    r = run_hook(tmp_path, cwd=ROOT, reason="clear")
    assert r.returncode == 0, r.stderr

    jpath = journal_path(tmp_path)
    assert jpath.exists()
    assert str(tmp_path) in str(jpath)                 # under the scratch dir...
    assert os.path.expanduser("~/.claude") not in str(jpath)  # ...never $HOME

    lines = read_lines(jpath)
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["reason"] == "clear"
    assert "ts" in entry and "cwd" in entry
    # cwd is a real git repo => git breadcrumbs present
    assert "branch" in entry
    assert "dirty_count" in entry
    assert isinstance(entry["dirty_count"], int)


def test_rotates_at_five_megabytes(tmp_path):
    jpath = journal_path(tmp_path)
    jpath.parent.mkdir(parents=True, exist_ok=True)
    jpath.write_text("x" * (5 * 1024 * 1024 + 10))  # over the 5MB cap

    r = run_hook(tmp_path, cwd=ROOT)
    assert r.returncode == 0, r.stderr

    rotated = jpath.parent / "journal.1.ndjson"
    assert rotated.exists()                 # old journal rotated aside
    assert len(read_lines(jpath)) == 1      # fresh journal has just the new line


def test_reindex_side_effect_indexes_a_mid_session_memory(tmp_path):
    # mem.py must be reachable at $BASE/cli/mem.py for the reindex to run.
    (tmp_path / "cli").mkdir(parents=True, exist_ok=True)
    shutil.copy(str(MEM), str(tmp_path / "cli" / "mem.py"))
    # a memory written "during" the session, before teardown
    mdir = tmp_path / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "fresh.md").write_text(
        "---\nname: Fresh session memory\ndescription: uniquetoken about widgets\n---\nbody",
        encoding="utf-8",
    )

    r = run_hook(tmp_path, cwd=ROOT)
    assert r.returncode == 0, r.stderr

    assert (mdir / "mem-index.db").exists()  # reindex created the index
    search = subprocess.run(
        [sys.executable, str(MEM), "search", "uniquetoken", "--json"],
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, CLAUDE_DIR=str(tmp_path)),
    )
    hits = json.loads(search.stdout)
    assert any(h["slug"] == "fresh" for h in hits)  # mid-session memory searchable


def test_gitless_cwd_is_safe(tmp_path):
    nongit = tmp_path / "not-a-repo"
    nongit.mkdir()
    r = run_hook(tmp_path, cwd=nongit, reason="other")
    assert r.returncode == 0, r.stderr
    entry = json.loads(read_lines(journal_path(tmp_path))[0])
    assert entry["reason"] == "other"
    assert "branch" not in entry       # no git => breadcrumbs omitted, line still written
    assert "git_root" not in entry


def test_slow_git_still_writes_the_breadcrumb_within_budget(tmp_path):
    # A fake `git` that sleeps longer than the per-call timeout: the total git budget
    # must bound all three calls so the breadcrumb is appended well under the 10s
    # SessionEnd kill (was: 3x5s of git could exceed 10s and lose the line entirely).
    import time
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "git").write_text("#!/bin/sh\nsleep 3\necho fake\n")
    (fakebin / "git").chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()

    env = dict(os.environ, CLAUDE_DIR=str(tmp_path),
               PATH=str(fakebin) + os.pathsep + os.environ["PATH"])
    payload = {"session_id": "s", "cwd": str(work), "reason": "clear"}
    start = time.monotonic()
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30, env=env)
    elapsed = time.monotonic() - start

    assert r.returncode == 0, r.stderr
    assert elapsed < 9, "git budget overran the SessionEnd window: %.1fs" % elapsed
    lines = read_lines(journal_path(tmp_path))
    assert len(lines) == 1                       # breadcrumb durable despite slow git
    entry = json.loads(lines[0])
    assert entry["reason"] == "clear" and "ts" in entry


def test_malformed_stdin_fails_open(tmp_path):
    r = run_hook(tmp_path, raw_stdin="not json")
    assert r.returncode == 0


def test_non_ascii_stdin_is_decoded_under_ascii_locale(tmp_path):
    # With the child's stdio forced to ASCII, a UTF-8 payload must still be decoded (the
    # hook reconfigures stdin to utf-8). Old cp1252/ascii defaults would UnicodeError,
    # the hook would fall back to data={}, and write a blank breadcrumb losing cwd/reason.
    payload = {"session_id": "s", "cwd": str(ROOT), "reason": "café 日本語 localización"}
    env = dict(os.environ, CLAUDE_DIR=str(tmp_path), PYTHONIOENCODING="ascii")
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=30, env=env,
    )
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in journal_path(tmp_path).read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["reason"] == "café 日本語 localización"  # decoded, not lost to {}
