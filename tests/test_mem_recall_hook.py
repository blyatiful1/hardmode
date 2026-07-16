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


def run_hook(claude_dir, state_dir, prompt="", session="s1", raw_stdin=None,
             env_extra=None):
    payload = {"prompt": prompt, "session_id": session}
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir), FABLE_STATE_DIR=str(state_dir))
    if env_extra:
        env.update(env_extra)
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


def test_mid_session_write_does_not_mute_recall(tmp_path):
    # A newer-than-index corpus file used to make recall go fully dark for the rest
    # of the session (any mid-session bank / native MEMORY.md write). It must NOT:
    # pointers are cheap, so slightly-stale hits still serve.
    seed_pooling_corpus(tmp_path, n=3)
    future = time.time() + 3600
    os.utime(Path(tmp_path) / "memory" / "pool1.md", (future, future))
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT)
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is not None  # still serves despite the newer file


def test_future_mtime_does_not_permanently_disable_recall(tmp_path):
    # A single far-future corpus mtime (Syncthing/rsync clock skew) used to disable
    # recall permanently, surviving even a rebuild. It must not.
    seed_pooling_corpus(tmp_path, n=3)
    far_future = time.time() + 10 * 365 * 86400
    os.utime(Path(tmp_path) / "memory" / "pool1.md", (far_future, far_future))
    build_index(tmp_path)  # rebuild — index mtime is "now", still < the 2035 file mtime
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT)
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is not None


def test_dead_pointer_is_not_surfaced(tmp_path):
    # A memory deleted mid-session (index not yet refreshed) must not send the caller
    # to a missing path — that single hit is dropped, not the whole recall.
    seed_pooling_corpus(tmp_path, n=1)
    (Path(tmp_path) / "memory" / "pool1.md").unlink()
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT)
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is None  # the only hit's file is gone => nothing to show


def test_non_ascii_prompt_recalls(tmp_path):
    # The query tokenizer must match the unicode61 index, or non-English prompts
    # silently recall nothing even when the content is indexed.
    gdir = Path(tmp_path) / "memory"
    write_memory(gdir, "cafe.md", "Café menu decision",
                 "localización 日本語 café notes", body=BODY_SENTINEL)
    build_index(tmp_path)
    r = run_hook(tmp_path, tmp_path / "state", "café 日本語 localización")
    assert r.returncode == 0, r.stderr
    ctx = injected_context(r)
    assert ctx is not None and "cafe.md" in ctx


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
    assert "…" in ctx                 # the 6000-char description was clamped with an ellipsis


def test_malformed_stdin_fails_open(tmp_path):
    seed_pooling_corpus(tmp_path, n=1)
    r = run_hook(tmp_path, tmp_path / "state", raw_stdin="not json")
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_substring_coincidence_stays_silent(tmp_path):
    # The relevance gate must count whole-token overlap, not substring containment.
    # Prompt keywords run/test only substring-match runbook/latest; that used to inflate
    # the overlap past the >=2 gate and surface this unrelated memory. Only "suite"
    # genuinely matches (overlap 1) => the gate must drop it.
    gdir = Path(tmp_path) / "memory"
    write_memory(gdir, "runbook.md", "Latest runbook",
                 "suite of latest tools and runbook procedures", body=BODY_SENTINEL)
    build_index(tmp_path)
    r = run_hook(tmp_path, tmp_path / "state", "run the test suite")
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is None


def test_min_overlap_env_knob_tightens_the_gate(tmp_path):
    # FABLE_MEM_MIN_OVERLAP raises the required keyword-overlap count; an otherwise
    # surfacing prompt goes silent when the gate is set above any hit's overlap.
    seed_pooling_corpus(tmp_path, n=3)
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT,
                 env_extra={"FABLE_MEM_MIN_OVERLAP": "99"})
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is None  # nothing clears an overlap of 99


def test_min_score_env_does_not_affect_recall(tmp_path):
    # FABLE_MEM_MIN_SCORE is mem.py search's bm25-scale knob, NOT the recall gate. It
    # used to be the SAME var: a huge value made the recall gate need 99 overlaps and
    # blanked recall. Now recall ignores it and still surfaces.
    seed_pooling_corpus(tmp_path, n=3)
    r = run_hook(tmp_path, tmp_path / "state", POOLING_PROMPT,
                 env_extra={"FABLE_MEM_MIN_SCORE": "99"})
    assert r.returncode == 0, r.stderr
    assert injected_context(r) is not None  # recall decoupled from the CLI score knob


def test_non_ascii_prompt_recalls_under_ascii_locale(tmp_path):
    # With the child's stdio forced to ASCII, a UTF-8 prompt must still be decoded (the
    # hook reconfigures stdin/stdout to utf-8) — old cp1252/ascii defaults would
    # UnicodeError and fail the hook open, silently dropping recall.
    gdir = Path(tmp_path) / "memory"
    write_memory(gdir, "cafe.md", "Café menu decision",
                 "localización 日本語 café notes", body=BODY_SENTINEL)
    build_index(tmp_path)
    payload = {"prompt": "café 日本語 localización", "session_id": "s1"}
    env = dict(os.environ, CLAUDE_DIR=str(tmp_path),
               FABLE_STATE_DIR=str(tmp_path / "state"), PYTHONIOENCODING="ascii")
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        # ensure_ascii=False so raw UTF-8 bytes hit the wire (the default escapes them to
        # \uXXXX, which is pure ASCII and would not exercise the decode path at all).
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=30, env=env,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout.decode("utf-8", "replace").strip()
    assert out, "expected injected pointers under an ascii locale"
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "cafe.md" in ctx
