# Unit tests for the fable-mem CLI (claude/cli/mem.py).
# The CLI is exercised as a real subprocess reading a scratch CLAUDE_DIR corpus —
# never imported — so every path/BASE resolution is proven the way the installed
# binary runs it. Each test gets its own tmp_path => its own CLAUDE_DIR, so runs
# never collide and the index/db always lands under the scratch dir, never $HOME.
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

MEM = Path(__file__).resolve().parents[1] / "claude" / "cli" / "mem.py"


def load_mem():
    """Import mem.py as a module for the few tests that must drive upsert() in-process
    (the concurrent-writer race can only be reproduced deterministically by controlling
    the statement interleaving). Every other test runs the CLI as a real subprocess."""
    spec = importlib.util.spec_from_file_location("fable_mem_under_test", str(MEM))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(claude_dir, *args, env_extra=None):
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(MEM), *args],
        capture_output=True, text=True, timeout=60, env=env,
    )


def write_memory(dir_path, filename, name, description="", body="", **fm):
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    front = {"name": name, "description": description, **fm}
    lines = ["---"]
    for k, v in front.items():
        lines.append("%s: %s" % (k, v))
    lines.append("---")
    lines.append(body)
    (dir_path / filename).write_text("\n".join(lines), encoding="utf-8")
    return dir_path / filename


def global_dir(claude_dir):
    return Path(claude_dir) / "memory"


def project_dir(claude_dir, project):
    return Path(claude_dir) / "projects" / project / "memory"


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------
def test_index_is_incremental_second_run_reinserts_nothing(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha decision", "first")
    write_memory(global_dir(tmp_path), "b.md", "Beta decision", "second")
    write_memory(global_dir(tmp_path), "c.md", "Gamma decision", "third")

    first = run(tmp_path, "index")
    assert first.returncode == 0, first.stderr
    assert "3 changed" in first.stdout

    second = run(tmp_path, "index")
    assert second.returncode == 0, second.stderr
    assert "0 changed" in second.stdout  # unchanged files are not re-inserted


def test_index_rebuild_reindexes_everything(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "x")
    write_memory(global_dir(tmp_path), "b.md", "Beta", "y")
    run(tmp_path, "index")
    r = run(tmp_path, "index", "--rebuild")
    assert r.returncode == 0, r.stderr
    assert "rebuilt" in r.stdout
    assert "2 changed" in r.stdout  # rebuild re-inserts every corpus file


def test_index_is_resilient_to_a_bad_file_in_the_batch(tmp_path):
    # A broken symlink among real memories must not sink the whole run: the
    # per-file loop skips it and commits the good files (batch resilience).
    gdir = global_dir(tmp_path)
    write_memory(gdir, "good1.md", "Good one", "ok")
    write_memory(gdir, "good2.md", "Good two", "ok")
    try:
        os.symlink(str(gdir / "does-not-exist.md"), str(gdir / "broken.md"))
    except OSError:
        # Creating a symlink needs SeCreateSymbolicLinkPrivilege on Windows (WinError
        # 1314 for an unelevated user); skip where symlinks are unavailable.
        pytest.skip("symlinks unavailable (needs privilege on Windows)")

    r = run(tmp_path, "index")
    assert r.returncode == 0, r.stderr
    stats = run(tmp_path, "stats")
    assert "global: 2" in stats.stdout  # both real files indexed; broken one skipped


# ---------------------------------------------------------------------------
# search — fts5 hit, scope filter, degraded LIKE fallback
# ---------------------------------------------------------------------------
def test_search_fts5_returns_the_matching_slug(tmp_path):
    write_memory(global_dir(tmp_path), "pooling.md",
                 "Postgres connection pooling",
                 "how we size the pgbouncer pool under load")
    write_memory(global_dir(tmp_path), "unrelated.md",
                 "Frontend routing", "react router notes")
    run(tmp_path, "index")

    r = run(tmp_path, "search", "postgres", "pooling", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)
    slugs = [h["slug"] for h in hits]
    assert "pooling" in slugs
    assert "unrelated" not in slugs


def test_fts_search_matches_short_tech_terms(tmp_path):
    # A 2-char token like "go"/"ci" must still match in the common fts5 mode. unicode61
    # token-matches (not substrings), so short tokens are safe there — the degraded LIKE
    # path filters them only to avoid substring noise. Forcing the two to share the
    # len>2 filter silently dropped every short-term query.
    write_memory(global_dir(tmp_path), "golang.md", "Go language notes", "go build tips")
    run(tmp_path, "index")
    hits = json.loads(run(tmp_path, "search", "go", "--json").stdout)
    assert any(h["slug"] == "golang" for h in hits), hits


def test_search_scope_filter_excludes_project_hits(tmp_path):
    write_memory(global_dir(tmp_path), "g.md",
                 "Kafka consumer lag", "global note about kafka lag")
    write_memory(project_dir(tmp_path, "repoA"), "p.md",
                 "Kafka consumer lag", "project note about kafka lag")
    run(tmp_path, "index")

    r = run(tmp_path, "search", "kafka", "lag", "--scope", "global", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)
    assert hits, "expected the global kafka memory"
    assert all(h["scope"] == "global" for h in hits)


def test_search_degrades_to_like_when_fts_forced_off(tmp_path):
    # Force the degradation seam: index + search both run with FTS disabled, so
    # the CLI must fall back to the plain-table LIKE scan and still find the hit.
    env = {"FABLE_MEM_FORCE_DEGRADED": "1"}
    write_memory(global_dir(tmp_path), "pooling.md",
                 "Postgres connection pooling",
                 "pgbouncer sizing under load")
    run(tmp_path, "index", env_extra=env)

    doc = run(tmp_path, "doctor", env_extra=env)
    assert "mode=degraded-like" in doc.stdout

    r = run(tmp_path, "search", "postgres", "pooling", "--json", env_extra=env)
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)
    assert any(h["slug"] == "pooling" for h in hits)


# ---------------------------------------------------------------------------
# show / stats
# ---------------------------------------------------------------------------
def test_show_prints_the_body_by_id(tmp_path):
    write_memory(global_dir(tmp_path), "d.md", "Decision X",
                 "the summary", body="BODYSENTINEL detail lives here")
    run(tmp_path, "index")
    hits = json.loads(run(tmp_path, "search", "decision", "--json").stdout)
    mid = hits[0]["id"]
    r = run(tmp_path, "show", str(mid))
    assert r.returncode == 0, r.stderr
    assert "Decision X" in r.stdout
    assert "BODYSENTINEL" in r.stdout


def test_stats_counts_per_scope(tmp_path):
    write_memory(global_dir(tmp_path), "g1.md", "G one")
    write_memory(global_dir(tmp_path), "g2.md", "G two")
    write_memory(project_dir(tmp_path, "repoA"), "p1.md", "P one")
    run(tmp_path, "index")
    r = run(tmp_path, "stats")
    assert r.returncode == 0, r.stderr
    assert "global: 2" in r.stdout
    assert "project: 1" in r.stdout


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------
def test_doctor_on_empty_corpus_exits_zero_and_creates_db(tmp_path):
    r = run(tmp_path, "doctor")
    assert r.returncode == 0, r.stderr
    assert (global_dir(tmp_path) / "mem-index.db").exists()


def test_doctor_privacy_flags_a_planted_marker(tmp_path):
    (global_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
    (global_dir(tmp_path) / "privacy.toml").write_text('patterns = ["ACME-*"]\n')
    write_memory(global_dir(tmp_path), "leak.md", "Leaky memory",
                 "mentions ACME-1234 which is a work marker")
    r = run(tmp_path, "doctor", "--privacy")
    assert r.returncode != 0
    assert "leak.md" in r.stdout


def test_doctor_privacy_clean_corpus_exits_zero(tmp_path):
    (global_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
    (global_dir(tmp_path) / "privacy.toml").write_text('patterns = ["ACME-*"]\n')
    write_memory(global_dir(tmp_path), "clean.md", "Clean memory",
                 "nothing sensitive here")
    r = run(tmp_path, "doctor", "--privacy")
    assert r.returncode == 0, r.stdout
    assert "clean" in r.stdout


def test_doctor_privacy_blank_pattern_does_not_false_positive(tmp_path):
    # A stray empty string in privacy.toml patterns compiles to a match-everything
    # regex; the blank-filter must drop it so a totally clean corpus stays clean
    # (was: phantom "FOUND 1 hit" on every file, exit 1).
    (global_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
    (global_dir(tmp_path) / "privacy.toml").write_text('patterns = ["", "  "]\n')
    write_memory(global_dir(tmp_path), "clean.md", "Clean memory",
                 "no markers at all here")
    r = run(tmp_path, "doctor", "--privacy")
    assert r.returncode == 0, r.stdout
    assert "FOUND" not in r.stdout


def test_doctor_privacy_warns_the_index_embeds_project_bodies(tmp_path):
    # CONF49: mem-index.db in the shareable memory dir stores project-memory bodies
    # verbatim; the privacy scan must warn about it rather than imply the dir is safe.
    write_memory(project_dir(tmp_path, "repoA"), "note.md", "Note", "some project detail")
    assert run(tmp_path, "index").returncode == 0  # creates mem-index.db under memory/
    r = run(tmp_path, "doctor", "--privacy")
    assert r.returncode == 0, r.stderr
    assert "embeds project-memory bodies" in r.stdout


def test_doctor_privacy_scans_the_ndjson_journal(tmp_path):
    # The SessionEnd journal (journal.ndjson) records cwd/branch verbatim into the
    # shared corpus dir; the detective sweep must see it, not only *.md.
    (global_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
    (global_dir(tmp_path) / "privacy.toml").write_text('patterns = ["ACME-*"]\n')
    (global_dir(tmp_path) / "journal.ndjson").write_text(
        '{"ts":"x","cwd":"/work/acme","branch":"feature/ACME-1234-fix"}\n')
    r = run(tmp_path, "doctor", "--privacy")
    assert r.returncode != 0
    assert "journal.ndjson" in r.stdout


# ---------------------------------------------------------------------------
# non-ASCII search — query tokenizer must match the unicode61 index
# ---------------------------------------------------------------------------
def test_search_matches_non_ascii_query(tmp_path):
    write_memory(global_dir(tmp_path), "cafe.md", "Café menu decision",
                 "localización notes 日本語 about the café")
    run(tmp_path, "index")
    for term in ("Café", "café", "日本語", "localización"):
        hits = json.loads(run(tmp_path, "search", term, "--json").stdout)
        assert any(h["slug"] == "cafe" for h in hits), "no hit for %r" % term


# ---------------------------------------------------------------------------
# corrupt index — disposable, so mutating commands self-heal, reads fail soft
# ---------------------------------------------------------------------------
def corrupt_the_db(claude_dir):
    db = global_dir(claude_dir) / "mem-index.db"
    db.write_bytes(os.urandom(4096))  # not a sqlite file anymore


def test_index_rebuild_recovers_from_a_corrupt_db(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha decision", "retry backoff")
    run(tmp_path, "index")
    corrupt_the_db(tmp_path)
    r = run(tmp_path, "index", "--rebuild")
    assert r.returncode == 0, r.stderr   # rebuild reconstructs from the corpus
    assert "rebuilt" in r.stdout
    hits = json.loads(run(tmp_path, "search", "retry", "--json").stdout)
    assert any(h["slug"] == "a" for h in hits)


def test_doctor_reports_a_corrupt_index_without_tracebacking(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "x")
    run(tmp_path, "index")
    corrupt_the_db(tmp_path)
    r = run(tmp_path, "doctor")
    assert r.returncode == 1
    assert "mode=corrupt" in r.stdout
    assert "rebuild" in r.stdout.lower()
    assert "Traceback" not in r.stderr


def test_search_on_a_corrupt_index_returns_no_hits(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "x")
    run(tmp_path, "index")
    corrupt_the_db(tmp_path)
    r = run(tmp_path, "search", "alpha", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []
    assert "Traceback" not in r.stderr


def test_stats_recreates_a_corrupt_index(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "x")
    run(tmp_path, "index")
    corrupt_the_db(tmp_path)
    r = run(tmp_path, "stats")
    assert r.returncode == 0, r.stderr   # heals the disposable index, reports empty
    assert "Traceback" not in r.stderr


def test_search_on_a_schemaless_index_returns_no_hits(tmp_path):
    # CONF48: a 0-byte (or otherwise schema-less) index file is a VALID sqlite db
    # with no `memories` table. search/show read that table directly and used to
    # traceback; they must fail soft like any corrupt index instead.
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "retry backoff")
    run(tmp_path, "index")
    (global_dir(tmp_path) / "mem-index.db").write_bytes(b"")  # schema-less, not garbage
    r = run(tmp_path, "search", "retry", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []
    assert "Traceback" not in r.stderr
    # and it self-heals on rebuild
    assert run(tmp_path, "index", "--rebuild").returncode == 0


# ---------------------------------------------------------------------------
# WAL + degraded escape hatch
# ---------------------------------------------------------------------------
def test_index_uses_wal_journal_mode(tmp_path):
    import sqlite3
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "x")
    run(tmp_path, "index")
    db = global_dir(tmp_path) / "mem-index.db"
    mode = sqlite3.connect(str(db)).execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"  # readers read a snapshot instead of blocking a writer


def test_force_degraded_search_never_serves_stale_fts(tmp_path):
    env = {"FABLE_MEM_FORCE_DEGRADED": "1"}
    # Build a real fts5 index containing a token...
    f = write_memory(global_dir(tmp_path), "a.md", "Lesson alpha", "quokkatoken sizing")
    run(tmp_path, "index", "--rebuild")
    # ...then remove the token from the corpus and rebuild in degraded mode.
    f.write_text("---\nname: Lesson alpha\ndescription: walrusword replaced\n---\nbody\n",
                 encoding="utf-8")
    run(tmp_path, "index", "--rebuild", env_extra=env)
    # A degraded search must reflect the fresh corpus, not the stale fts5 rows.
    stale = json.loads(run(tmp_path, "search", "quokkatoken", "--json", env_extra=env).stdout)
    assert stale == []
    fresh = json.loads(run(tmp_path, "search", "walrusword", "--json", env_extra=env).stdout)
    assert any(h["slug"] == "a" for h in fresh)


# ---------------------------------------------------------------------------
# gc-scan — mechanical proposals (read-only)
# ---------------------------------------------------------------------------
def test_gc_scan_flags_near_duplicate(tmp_path):
    write_memory(global_dir(tmp_path), "one.md", "Identical title here", "a")
    write_memory(global_dir(tmp_path), "two.md", "Identical title here", "b")
    r = run(tmp_path, "gc-scan", "--json")
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["near_duplicates"], "expected a near-duplicate pair"


def test_gc_scan_does_not_flag_memory_md_filename_collisions(tmp_path):
    # CONF50: native per-project MEMORY.md files have no frontmatter `name:` and fall
    # back to the basename "MEMORY". Matching on that fallback produced an N-choose-2
    # explosion of bogus "identical name" pairs across unrelated projects. Only
    # DECLARED names should collide.
    for proj in ("repoA", "repoB", "repoC"):
        d = project_dir(tmp_path, proj)
        d.mkdir(parents=True, exist_ok=True)
        (d / "MEMORY.md").write_text("no frontmatter here\njust notes\n", encoding="utf-8")
    r = run(tmp_path, "gc-scan", "--json")
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    name_pairs = [p for p in report["near_duplicates"] if p["reason"] == "identical name"]
    assert name_pairs == [], f"filename-fallback names must not collide: {name_pairs}"


def test_gc_scan_does_not_flag_bare_now_as_relative_date(tmp_path):
    # CONF53: "now"/"recently" in ordinary prose ("we now use tabs") is not a relative
    # date and must not trigger a rewrite proposal.
    write_memory(global_dir(tmp_path), "prose.md", "Convention",
                 "style", body="we now use tabs; this was recently agreed")
    r = run(tmp_path, "gc-scan", "--json")
    report = json.loads(r.stdout)
    paths = [d["path"] for d in report["relative_dates"]]
    assert not any("prose.md" in p for p in paths), report["relative_dates"]


def test_gc_scan_flags_stale_project_memory(tmp_path):
    old = (date.today() - timedelta(days=120)).isoformat()
    write_memory(project_dir(tmp_path, "repoA"), "old.md", "Stale note",
                 "aging out", created=old)
    r = run(tmp_path, "gc-scan", "--json")
    report = json.loads(r.stdout)
    paths = [s["path"] for s in report["stale"]]
    assert any("old.md" in p for p in paths)


def test_gc_scan_flags_relative_date(tmp_path):
    write_memory(global_dir(tmp_path), "rel.md", "Relative dater",
                 "we shipped it", body="fixed the deadlock yesterday afternoon")
    r = run(tmp_path, "gc-scan", "--json")
    report = json.loads(r.stdout)
    paths = [d["path"] for d in report["relative_dates"]]
    assert any("rel.md" in p for p in paths)


def test_gc_scan_flags_same_topic_pair(tmp_path):
    write_memory(global_dir(tmp_path), "t1.md",
                 "Kafka consumer rebalancing", "consumer group tuning")
    write_memory(global_dir(tmp_path), "t2.md",
                 "Kafka consumer offsets", "consumer offset commits")
    r = run(tmp_path, "gc-scan", "--json")
    report = json.loads(r.stdout)
    assert report["same_topic_pairs"], "expected a same-topic pair"


def test_gc_scan_does_not_mutate_the_corpus(tmp_path):
    f = write_memory(global_dir(tmp_path), "keep.md", "Keeper",
                     "unchanged", body="original body")
    before = f.read_text()
    run(tmp_path, "gc-scan", "--json")
    assert f.read_text() == before  # proposals only — never edits/deletes


# ---------------------------------------------------------------------------
# BASE honors CLAUDE_DIR — the db lives under the scratch dir, never $HOME
# ---------------------------------------------------------------------------
def test_base_honors_claude_dir(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha", "x")
    r = run(tmp_path, "index")
    assert r.returncode == 0, r.stderr
    db = global_dir(tmp_path) / "mem-index.db"
    assert db.exists()

    stats = run(tmp_path, "stats")
    assert str(db) in stats.stdout  # reports the scratch-dir db...
    assert os.path.expanduser("~/.claude") not in stats.stdout  # ...never ~/.claude


# ---------------------------------------------------------------------------
# concurrent writers — atomic UPSERT must not crash the loser on a UNIQUE race
# ---------------------------------------------------------------------------
def _rec(path):
    return {"path": str(path), "scope": "global", "project": "", "name": "Race",
            "description": "d", "type": "", "created": "", "verified": "",
            "visibility": "", "mtime": 1.0, "body": "b"}


def test_upsert_survives_a_concurrent_writer_racing_the_same_path(tmp_path):
    # Two writers both observe a path absent, then both INSERT it. The old check-then-act
    # upsert crashed the loser with `UNIQUE constraint failed: memories.path`. Reproduced
    # deterministically: a proxy connection lets a second writer INSERT+commit the SAME
    # path in the instant writer A is about to INSERT — the exact two-process window.
    mem = load_mem()
    base = str(tmp_path)
    conn, mode = mem.open_db(base=base)
    racer, _ = mem.open_db(base=base)
    rec = _rec(tmp_path / "memory" / "race.md")
    state = {"raced": False}

    class RacingConn:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a, **k):
            if not state["raced"] and sql.startswith("INSERT INTO memories(path"):
                state["raced"] = True
                mem.upsert(racer, mode, rec)   # the concurrent winner commits first
                racer.commit()
            return self._real.execute(sql, *a, **k)

        def commit(self):
            return self._real.commit()

    # Must NOT raise: ON CONFLICT folds the collision into an UPDATE.
    mem.upsert(RacingConn(conn), mode, rec)
    conn.commit()
    assert state["raced"], "the race window was never exercised"
    n = conn.execute("SELECT COUNT(*) FROM memories WHERE path=?",
                     (rec["path"],)).fetchone()[0]
    assert n == 1  # both writers converge on a single row, no duplicate/crash
    conn.close()
    racer.close()


# ---------------------------------------------------------------------------
# degraded search — whole-token matching, not substring containment
# ---------------------------------------------------------------------------
def test_degraded_search_matches_whole_tokens_not_substrings(tmp_path):
    # "test" must not match because it is a substring of "latest"; the degraded LIKE
    # path used to count substring containment, inflating relevance with coincidences.
    env = {"FABLE_MEM_FORCE_DEGRADED": "1"}
    write_memory(global_dir(tmp_path), "runbook.md", "Latest runbook",
                 "runbook procedures for latest tools")
    run(tmp_path, "index", env_extra=env)
    hits = json.loads(run(tmp_path, "search", "test", "--json", env_extra=env).stdout)
    assert hits == [], hits  # only a substring of 'latest' — not a genuine token hit
    # a genuine token still matches
    real = json.loads(run(tmp_path, "search", "runbook", "--json", env_extra=env).stdout)
    assert any(h["slug"] == "runbook" for h in real)


# ---------------------------------------------------------------------------
# FABLE_MEM_MIN_SCORE / FABLE_MEM_MIN_OVERLAP are separate, non-crossing knobs
# ---------------------------------------------------------------------------
def test_min_score_env_filters_cli_search(tmp_path):
    write_memory(global_dir(tmp_path), "a.md", "Alpha decision", "retry backoff")
    run(tmp_path, "index")
    base = json.loads(run(tmp_path, "search", "alpha", "--json").stdout)
    assert base  # normally a hit
    filtered = json.loads(run(tmp_path, "search", "alpha", "--json",
                              env_extra={"FABLE_MEM_MIN_SCORE": "1000000000"}).stdout)
    assert filtered == []  # bm25-scale threshold drops everything


def test_min_overlap_env_does_not_affect_cli_search(tmp_path):
    # FABLE_MEM_MIN_OVERLAP is the recall hook's keyword-count knob; mem.py search must
    # ignore it (it filters on FABLE_MEM_MIN_SCORE only). Proves the two are decoupled.
    write_memory(global_dir(tmp_path), "a.md", "Alpha decision", "retry backoff")
    run(tmp_path, "index")
    hits = json.loads(run(tmp_path, "search", "alpha", "--json",
                          env_extra={"FABLE_MEM_MIN_OVERLAP": "1000000000"}).stdout)
    assert hits  # CLI search unaffected by the recall knob
