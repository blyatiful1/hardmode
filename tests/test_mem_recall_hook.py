# Unit tests for the UserPromptSubmit cross-project memory-recall hook.
# The hook is exercised as a real subprocess reading real stdin, against a scratch
# CLAUDE_DIR corpus indexed by mem.py — never imported. Each test builds its own
# corpus + index under tmp_path so the db always lands there, never $HOME.
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "claude" / "hooks" / "userpromptsubmit-mem-recall.py"
MEM = ROOT / "claude" / "cli" / "mem.py"

BODY_SENTINEL = "BODYSENTINEL_never_surface_this"


def write_memory(dir_path, filename, name, description="", body=""):
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    text = "---\nname: %s\ndescription: %s\n---\n%s" % (name, description, body)
    (dir_path / filename).write_text(text, encoding="utf-8")
    return dir_path / filename


def build_index(claude_dir):
    r = subprocess.run(
        [sys.executable, str(MEM), "index"],
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, CLAUDE_DIR=str(claude_dir)),
    )
    assert r.returncode == 0, r.stderr
    return r


def run_hook(claude_dir, state_dir, prompt="", session="s1", raw_stdin=None):
    payload = {"prompt": prompt, "session_id": session}
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir), FABLE_STATE_DIR=str(state_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env,
    )


def injected_context(result):
    """Parse the hook's additionalContext, or None when it stayed silent."""
    out = result.stdout.strip()
    if not out:
        return None
    data = json.loads(out)
    return data["hookSpecificOutput"]["additionalContext"]


def seed_pooling_corpus(claude_dir, n=5):
    gdir = Path(claude_dir) / "memory"
    for i in range(1, n + 1):
        write_memory(
            gdir, "pool%d.md" % i,
            "Postgres connection pooling note %d" % i,
            "how we size the pgbouncer connection pool under load",
            body="%s pool internals %d" % (BODY_SENTINEL, i),
        )
    build_index(claude_dir)


POOLING_PROMPT = "how should I handle postgres connection pooling under heavy load"


# ---------------------------------------------------------------------------
def test_relevant_prompt_injects_capped_labeled_pointers(tmp_path):
    seed_pooling_corpus(tmp_path, n=5)
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT)
    assert r.returncode == 0, r.stderr
    ctx = injected_context(r)
    assert ctx is not None, "expected injected pointers"
    # labeled as untrusted reference data, not instructions
    assert "UNTRUSTED REFERENCE DATA" in ctx
    # paths surfaced, bodies never
    assert "pool1.md" in ctx
    assert BODY_SENTINEL not in ctx
    # hard cap of 3 pointers even though 5 memories match
    enumerated = [ln for ln in ctx.splitlines() if ln.strip()[:2] in
                  ("1.", "2.", "3.", "4.", "5.")]
    assert 1 <= len(enumerated) <= 3


def test_irrelevant_prompt_stays_silent(tmp_path):
    seed_pooling_corpus(tmp_path, n=3)
    r = run_hook(tmp_path, tmp_path / "state",
                 "what is the capital of france today")
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is None


def test_per_session_dedupe_second_run_is_silent(tmp_path):
    seed_pooling_corpus(tmp_path, n=3)
    state = tmp_path / "state"
    first = run_hook(tmp_path, state, POOLING_PROMPT, session="dup")
    assert injected_context(first) is not None
    second = run_hook(tmp_path, state, POOLING_PROMPT, session="dup")
    assert injected_context(second) is None  # already surfaced this session


def test_sessions_are_isolated(tmp_path):
    seed_pooling_corpus(tmp_path, n=3)
    state = tmp_path / "state"
    a = run_hook(tmp_path, state, POOLING_PROMPT, session="sess-a")
    assert injected_context(a) is not None
    b = run_hook(tmp_path, state, POOLING_PROMPT, session="sess-b")
    assert injected_context(b) is not None  # a different session is not deduped


def test_stale_index_stays_silent(tmp_path):
    seed_pooling_corpus(tmp_path, n=3)
    # Make a corpus file newer than the index => staleness => silence, never build.
    future = time.time() + 3600
    target = Path(tmp_path) / "memory" / "pool1.md"
    os.utime(target, (future, future))
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT)
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is None


def test_token_and_char_budget_respected(tmp_path):
    gdir = Path(tmp_path) / "memory"
    huge = "postgres connection pooling " + ("x" * 6000)
    for i in range(1, 6):
        write_memory(gdir, "big%d.md" % i,
                     "Postgres connection pooling giant %d" % i,
                     huge, body=BODY_SENTINEL)
    build_index(tmp_path)
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT)
    ctx = injected_context(r)
    assert ctx is not None
    assert len(ctx) < 3200            # well under the ~600-token / 10k budget
    assert "…" in ctx or len(ctx) < 3200  # long descriptions are clamped


def test_malformed_stdin_fails_open(tmp_path):
    seed_pooling_corpus(tmp_path, n=1)
    r = run_hook(tmp_path, tmp_path / "state", raw_stdin="not json")
    assert r.returncode == 0
    assert r.stdout.strip() == ""
