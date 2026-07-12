#!/usr/bin/env python3
"""fable-mem CLI — cross-project persistent-memory index (fable-protocol, L2).

WHY THIS EXISTS
    Claude Code's native auto-memory is per-git-repo (`~/.claude/projects/<p>/memory/`)
    and only MEMORY.md auto-loads. There is no shared, searchable, CROSS-project store.
    This CLI layers one on top: it indexes the L1 global corpus (`$BASE/memory/*.md`)
    AND every native per-repo corpus (`$BASE/projects/*/memory/*.md`) into a local
    sqlite index, and exposes keyword recall over all of them. It is invoked as
    `python3 ~/.claude/cli/mem.py <subcommand>` — stdlib + sqlite3 ONLY, no pip/venv,
    because the harness runs a bare `python3`.

    Subcommands: index · search · show · stats · doctor · gc-scan.

FAIL-OPEN / SAFETY POSTURE
    Unlike a session hook, this is a user/side-effect CLI, so it returns MEANINGFUL
    exit codes (0 ok, 1 problem/dirty) rather than blindly exiting 0 — `doctor --privacy`
    is USELESS if it can't signal a leak with a non-zero code. But it never mutates the
    corpus: `index`/`gc-scan` only ever write the sqlite index, never a memory file, and
    `gc-scan`/`memory-gc` propose, never delete. The index is disposable — `--rebuild`
    reconstructs it from the corpus at any time.

BASE RESOLUTION (never hardcode ~/.claude)
    BASE = os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude")
    global corpus  = $BASE/memory/*.md                      (scope=global)
    project corpora= $BASE/projects/*/memory/*.md           (scope=project, git-root derived)
    sqlite index   = $BASE/memory/mem-index.db
    privacy.toml   = $BASE/memory/privacy.toml
    So every proof/doctor smoke run under a scratch CLAUDE_DIR operates on that scratch
    dir, not the CI runner's real HOME.

FTS5
    Availability is probed at DB-open (`CREATE VIRTUAL TABLE ... USING fts5` in a try).
    Present -> fast bm25 keyword recall. Missing (or FABLE_MEM_FORCE_DEGRADED=1) ->
    graceful degradation to a plain-table LIKE scan. `doctor` reports the active mode
    (`fts5` / `degraded-like`). Degraded mode is a FALLBACK, not a target.
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date

DB_NAME = "mem-index.db"
PRIVACY_TOML = "privacy.toml"
STALE_DAYS = 90                 # project memories older than this are gc-scan candidates
DEFAULT_LIMIT = 10

# Relative-date offenders — "yesterday" is meaningless next session (postmortem hygiene).
# Deliberately does NOT include a bare "now" or "recently": both appear constantly in
# ordinary prose ("we now use tabs"), and gc dispatched a rewrite agent for every one —
# a high-frequency false positive (CONF53). Only unambiguous time-anchors are flagged.
REL_DATE = re.compile(
    r"\b(?:yesterday|today|tomorrow|tonight|"
    r"last\s+(?:night|week|month|year|time)|"
    r"next\s+(?:week|month|year|time)|"
    r"this\s+(?:morning|afternoon|evening|week|month|year)|"
    r"a\s+(?:few\s+)?(?:day|week|month|year)s?\s+ago|"
    r"\d+\s+(?:day|week|month|year)s?\s+ago|"
    r"just\s+now|earlier\s+today)\b",
    re.IGNORECASE,
)

STOPWORDS = frozenset(
    "the a an and or of to in for on with is are be was were this that these those "
    "it its as at by from into over under about not no do does did done how why what "
    "when where which who whom you your we our they their he she his her i me my".split()
)


# ---------------------------------------------------------------------------
# BASE / path resolution
# ---------------------------------------------------------------------------
def base_dir():
    return os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude")


def memory_dir(base=None):
    return os.path.join(base or base_dir(), "memory")


def db_path(base=None):
    return os.path.join(memory_dir(base), DB_NAME)


def privacy_path(base=None):
    return os.path.join(memory_dir(base), PRIVACY_TOML)


# ---------------------------------------------------------------------------
# Frontmatter parsing (postmortem convention: name, description, type,
# created/verified, visibility; type may live under a metadata: block)
# ---------------------------------------------------------------------------
def _strip_val(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def parse_yaml_block(lines):
    """Minimal one-level YAML: flat `key: value` plus a single nested `metadata:` block."""
    fm = {}
    parent = None
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent > 0 and parent:
            m = re.match(r"\s+([A-Za-z0-9_.-]+):\s*(.*)$", ln)
            if m:
                fm[parent + "." + m.group(1)] = _strip_val(m.group(2))
            continue
        m = re.match(r"([A-Za-z0-9_.-]+):\s*(.*)$", ln)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if val.strip() == "":
            parent = key
        else:
            parent = None
            fm[key] = _strip_val(val)
    # Fold metadata.<k> down to <k> when the flat key is absent.
    for k in ("type", "created", "verified", "visibility", "name", "description"):
        if k not in fm and ("metadata." + k) in fm:
            fm[k] = fm["metadata." + k]
    return fm


def split_frontmatter(text):
    if text.startswith("---"):
        lines = text.splitlines()
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return parse_yaml_block(lines[1:i]), "\n".join(lines[i + 1:])
    return {}, text


def parse_file(path, scope, project, mtime):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    fm, body = split_frontmatter(text)
    name = fm.get("name") or os.path.splitext(os.path.basename(path))[0]
    return {
        "path": path, "scope": scope, "project": project,
        "name": name, "description": fm.get("description", ""),
        "type": fm.get("type", ""), "created": fm.get("created", ""),
        "verified": fm.get("verified", ""), "visibility": fm.get("visibility", ""),
        "mtime": mtime, "body": body,
    }


# ---------------------------------------------------------------------------
# DB open + FTS5 probe/degradation
# ---------------------------------------------------------------------------
class CorruptIndex(Exception):
    """The index file exists but is not a readable sqlite database (partial write,
    disk-full mid-write, a sync/backup tool clobbering it). The index is DISPOSABLE,
    so mutating commands unlink+recreate it and read paths handle it gracefully —
    neither should traceback."""


def _enable_wal(conn):
    """Best-effort WAL. WAL lets the read-only recall hook read a snapshot CONCURRENTLY
    with an index writer instead of blocking on the writer's exclusive lock (rollback
    mode) and failing open under a full rebuild. Never confuse a WAL-unsupported
    filesystem (some network mounts) with corruption — corruption is detected by
    ensure_schema's CREATE, not here — so this is best-effort and swallows errors."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass  # WAL unavailable on this FS — rollback journal still works


def _fts_available(conn):
    if os.environ.get("FABLE_MEM_FORCE_DEGRADED") == "1":
        return False
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5("
            "name, description, body, tokenize='unicode61')"
        )
        return True
    except sqlite3.OperationalError:
        return False


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories("
        " id INTEGER PRIMARY KEY,"
        " path TEXT UNIQUE NOT NULL,"
        " scope TEXT NOT NULL DEFAULT '',"
        " project TEXT NOT NULL DEFAULT '',"
        " name TEXT NOT NULL DEFAULT '',"
        " description TEXT NOT NULL DEFAULT '',"
        " type TEXT NOT NULL DEFAULT '',"
        " created TEXT NOT NULL DEFAULT '',"
        " verified TEXT NOT NULL DEFAULT '',"
        " visibility TEXT NOT NULL DEFAULT '',"
        " mtime REAL NOT NULL DEFAULT 0,"
        " body TEXT NOT NULL DEFAULT '')"
    )
    mode = "fts5" if _fts_available(conn) else "degraded-like"
    conn.commit()
    return mode


def open_db(base=None, readonly=False, recreate_on_corrupt=False):
    """Return (conn, mode). Creates the DB (and $BASE/memory/) if absent.

    A corrupt/unreadable index raises sqlite3.DatabaseError on the first statement.
    Because the index is DISPOSABLE, a mutating caller (index/stats/gc-scan) passes
    recreate_on_corrupt=True so it unlinks+recreates the file and succeeds; read paths
    (search/show/doctor) leave recreate off and catch CorruptIndex to fail gracefully
    instead of tracebacking. The readonly path also honors FABLE_MEM_FORCE_DEGRADED so
    the degraded escape hatch actually forces a degraded (LIKE) search instead of
    silently ranking against a possibly-stale fts5 table."""
    path = db_path(base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if readonly and os.path.exists(path):
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
        forced_degraded = os.environ.get("FABLE_MEM_FORCE_DEGRADED") == "1"
        # A schema-LESS but otherwise valid sqlite file (0-byte from touch/disk-full,
        # or a sync tool clobbering it) has no `memories` table. Search/show query it
        # directly, so probe it here and treat its absence as a corrupt/disposable
        # index rather than letting the caller traceback later (CONF48). Do this even
        # under FABLE_MEM_FORCE_DEGRADED, whose path also reads `memories`.
        try:
            conn.execute("SELECT 1 FROM memories LIMIT 1")
        except sqlite3.OperationalError:   # no such table: memories
            conn.close()
            raise CorruptIndex(path)
        except sqlite3.DatabaseError:      # file is not a database => corrupt
            conn.close()
            raise CorruptIndex(path)
        if forced_degraded:
            return conn, "degraded-like"
        mode = "fts5"
        try:
            conn.execute("SELECT 1 FROM mem_fts LIMIT 1")
        except sqlite3.OperationalError:   # fts table absent => degraded search
            mode = "degraded-like"
        return conn, mode
    conn = sqlite3.connect(path, timeout=10)
    try:
        mode = ensure_schema(conn)
    except sqlite3.DatabaseError:
        conn.close()
        if not recreate_on_corrupt:
            raise CorruptIndex(path)
        try:
            os.remove(path)                # disposable — reconstruct from the corpus
            for side in (path + "-wal", path + "-shm"):
                if os.path.exists(side):
                    os.remove(side)        # drop stale WAL sidecars of the dead db
        except OSError:
            raise CorruptIndex(path)
        conn = sqlite3.connect(path, timeout=10)
        mode = ensure_schema(conn)
    _enable_wal(conn)
    return conn, mode


# ---------------------------------------------------------------------------
# Corpus discovery + indexing
# ---------------------------------------------------------------------------
def discover(base=None):
    """Yield (path, scope, project) for every corpus .md file (sorted, stable)."""
    base = base or base_dir()
    out = []
    for p in sorted(glob.glob(os.path.join(memory_dir(base), "*.md"))):
        out.append((p, "global", ""))
    for mdir in sorted(glob.glob(os.path.join(base, "projects", "*", "memory"))):
        project = os.path.basename(os.path.dirname(mdir))
        for p in sorted(glob.glob(os.path.join(mdir, "*.md"))):
            out.append((p, "project", project))
    return out


def _fts_write(conn, mode, mid, rec):
    if mode != "fts5":
        return
    conn.execute("DELETE FROM mem_fts WHERE rowid=?", (mid,))
    conn.execute(
        "INSERT INTO mem_fts(rowid, name, description, body) VALUES(?,?,?,?)",
        (mid, rec["name"], rec["description"], rec["body"]),
    )


def upsert(conn, mode, rec):
    row = conn.execute("SELECT id FROM memories WHERE path=?", (rec["path"],)).fetchone()
    cols = ("scope", "project", "name", "description", "type",
            "created", "verified", "visibility", "mtime", "body")
    if row:
        mid = row[0]
        conn.execute(
            "UPDATE memories SET " + ",".join(c + "=?" for c in cols) + " WHERE id=?",
            tuple(rec[c] for c in cols) + (mid,),
        )
    else:
        cur = conn.execute(
            "INSERT INTO memories(path," + ",".join(cols) + ") VALUES(?," +
            ",".join("?" for _ in cols) + ")",
            (rec["path"],) + tuple(rec[c] for c in cols),
        )
        mid = cur.lastrowid
    _fts_write(conn, mode, mid, rec)
    return mid


def run_index(conn, mode, rebuild=False):
    """Index the corpus. Commits per file so a timeout-kill preserves partial progress
    and the next incremental run resumes instead of restarting from empty."""
    if rebuild:
        conn.execute("DELETE FROM memories")
        if mode == "fts5":
            conn.execute("DELETE FROM mem_fts")
        else:
            # Degraded rebuild: clear any stale rows a prior fts5 build left behind so
            # a later readonly search (which detects mode by the table's presence) can
            # never rank against orphaned FTS content. Best-effort — the table may not
            # exist at all in a from-scratch degraded corpus.
            try:
                conn.execute("DELETE FROM mem_fts")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    seen = set()
    changed = 0
    for path, scope, project in discover():
        seen.add(path)
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        if not rebuild:
            row = conn.execute("SELECT mtime FROM memories WHERE path=?", (path,)).fetchone()
            if row is not None and abs(row[0] - mt) < 1e-6:
                continue  # unchanged since last index
        upsert(conn, mode, parse_file(path, scope, project, mt))
        conn.commit()  # per-file / small-batch commit — Major-1
        changed += 1
    # Prune rows whose file has vanished.
    pruned = 0
    for mid, p in conn.execute("SELECT id, path FROM memories").fetchall():
        if p not in seen:
            conn.execute("DELETE FROM memories WHERE id=?", (mid,))
            if mode == "fts5":
                conn.execute("DELETE FROM mem_fts WHERE rowid=?", (mid,))
            pruned += 1
    if pruned:
        conn.commit()
    return changed, len(seen), pruned


def cmd_index(args):
    # Mutating command: a corrupt index is unlinked+recreated so `index --rebuild`
    # genuinely "reconstructs it from the corpus at any time" (the module guarantee),
    # and the SessionEnd reindex self-heals instead of leaving recall permanently dead.
    conn, mode = open_db(recreate_on_corrupt=True)
    changed, total, pruned = run_index(conn, mode, rebuild=args.rebuild)
    conn.close()
    verb = "rebuilt" if args.rebuild else "indexed"
    print("%s: %d changed, %d total in corpus, %d pruned (mode=%s)"
          % (verb, changed, total, pruned, mode))
    return 0


# ---------------------------------------------------------------------------
# search / show / stats
# ---------------------------------------------------------------------------
# Unicode word token: letters/digits across ALL scripts (accented Latin, CJK, …),
# excluding "_", to MATCH the fts5 unicode61 tokenizer the index is built with. An
# ASCII-only [A-Za-z0-9]+ truncates "Café" to "Caf" (never matches indexed "café")
# and yields zero tokens for "日本語", silently returning no hits for non-English queries.
WORD = re.compile(r"[^\W_]+", re.UNICODE)


def keywords(text):
    return [t for t in WORD.findall(text.lower())
            if len(t) > 2 and t not in STOPWORDS]


def _fts_match(query):
    # Use the SAME token filter as the degraded path (keywords(): len>2, stopwords
    # dropped) so fts5 and LIKE modes agree on which tokens count — otherwise the same
    # query could hit in one mode and return nothing in the other (CONF57).
    toks = keywords(query)
    if not toks:
        return None
    return " OR ".join('"%s"' % t for t in toks)


def _min_score():
    raw = os.environ.get("FABLE_MEM_MIN_SCORE")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def slug_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def search(base_conn_mode, query, scope="all", limit=DEFAULT_LIMIT):
    conn, mode = base_conn_mode
    scope_ok = scope in ("global", "project")
    hits = []
    if mode == "fts5":
        match = _fts_match(query)
        if match is None:
            return []
        sql = ("SELECT m.id, m.name, m.description, m.path, m.scope, bm25(mem_fts) "
               "FROM mem_fts JOIN memories m ON m.id = mem_fts.rowid "
               "WHERE mem_fts MATCH ?")
        params = [match]
        if scope_ok:
            sql += " AND m.scope=?"
            params.append(scope)
        sql += " ORDER BY bm25(mem_fts) LIMIT ?"
        params.append(limit)
        for mid, name, desc, path, sc, rank in conn.execute(sql, params):
            hits.append((mid, name, desc, path, sc, round(-float(rank), 4)))
    else:
        toks = keywords(query)
        if not toks:
            return []
        rows = conn.execute(
            "SELECT id, name, description, path, scope, body FROM memories"
        ).fetchall()
        scored = []
        for mid, name, desc, path, sc, body in rows:
            if scope_ok and sc != scope:
                continue
            hay = ("%s %s %s" % (name, desc, body)).lower()
            matched = sum(1 for t in toks if t in hay)
            if not matched:
                continue
            weight = sum(hay.count(t) for t in toks)
            scored.append((matched, weight, mid, name, desc, path, sc))
        scored.sort(key=lambda r: (r[0], r[1]), reverse=True)
        for matched, weight, mid, name, desc, path, sc in scored[:limit]:
            hits.append((mid, name, desc, path, sc, float(matched)))
    lo = _min_score()
    if lo is not None:
        hits = [h for h in hits if h[5] >= lo]
    return hits


def cmd_search(args):
    query = " ".join(args.query)
    try:
        conn, mode = open_db(readonly=True)
    except CorruptIndex:
        # Read path: a corrupt index yields no hits (recoverable via `index --rebuild`).
        if args.json:
            print("[]")
        return 0
    hits = search((conn, mode), query, scope=args.scope, limit=args.limit)
    conn.close()
    if args.json:
        print(json.dumps([
            {"id": mid, "name": name, "description": desc, "path": path,
             "scope": sc, "slug": slug_of(path), "score": score}
            for mid, name, desc, path, sc, score in hits
        ]))
        return 0
    if not hits:
        return 0
    for mid, name, desc, path, sc, score in hits:
        print("[%d] %s  (%s, score=%s)" % (mid, name, sc, score))
        if desc:
            print("    %s" % desc)
        print("    %s" % path)
    return 0


def cmd_show(args):
    try:
        conn, _ = open_db(readonly=True)
    except CorruptIndex:
        print("index unreadable — run `mem.py index --rebuild` to reconstruct it",
              file=sys.stderr)
        return 1
    row = conn.execute(
        "SELECT id, name, description, path, scope, project, type, created, "
        "verified, visibility, mtime, body FROM memories WHERE id=?", (args.id,)
    ).fetchone()
    conn.close()
    if not row:
        print("no memory with id=%d" % args.id, file=sys.stderr)
        return 1
    (mid, name, desc, path, sc, proj, typ, created, verified, visibility, mtime, body) = row
    print("id:          %d" % mid)
    print("name:        %s" % name)
    print("scope:       %s%s" % (sc, (" (%s)" % proj) if proj else ""))
    print("type:        %s" % typ)
    print("created:     %s" % created)
    print("verified:    %s" % verified)
    print("visibility:  %s" % visibility)
    print("path:        %s" % path)
    if desc:
        print("description: %s" % desc)
    print("---")
    print(body)
    return 0


def cmd_stats(args):
    conn, mode = open_db(recreate_on_corrupt=True)
    g = conn.execute("SELECT COUNT(*) FROM memories WHERE scope='global'").fetchone()[0]
    p = conn.execute("SELECT COUNT(*) FROM memories WHERE scope='project'").fetchone()[0]
    projects = conn.execute(
        "SELECT COUNT(DISTINCT project) FROM memories WHERE scope='project' AND project<>''"
    ).fetchone()[0]
    conn.close()
    print("memories: %d total (global: %d, project: %d)" % (g + p, g, p))
    print("projects indexed: %d" % projects)
    print("mode: %s" % mode)
    print("db: %s" % db_path())
    return 0


# ---------------------------------------------------------------------------
# doctor  (+ --privacy detective scan)
# ---------------------------------------------------------------------------
def compile_marker(pattern):
    """Work-marker glob -> unanchored regex. `*` matches a run of non-space chars,
    everything else is literal. e.g. 'ACME-*' matches 'ACME-1234' anywhere in text."""
    parts = str(pattern).split("*")
    return re.compile(r"\S*".join(re.escape(p) for p in parts))


def load_privacy_patterns(base=None):
    """Return (patterns, path, note). note is None on success, else a reason string."""
    path = privacy_path(base)
    if not os.path.exists(path):
        return [], path, "missing"
    try:
        import tomllib
    except ImportError:
        return [], path, "no-tomllib"
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:  # malformed toml — report, don't crash
        return [], path, "parse-error: %s" % exc
    pats = data.get("patterns") or []
    if not isinstance(pats, list):
        return [], path, "patterns-not-a-list"
    # Drop blank/whitespace-only patterns: compile_marker("") -> a regex that matches
    # (nearly) every file, which would make `doctor --privacy` false-positive a leak on
    # a totally clean corpus. Mirrors the guard's load_patterns() `.strip()` filter.
    return [str(x) for x in pats if str(x).strip()], path, None


def privacy_scan(base=None):
    """Scan the GLOBAL corpus for work markers. Returns (exit_code, lines)."""
    base = base or base_dir()
    pats, path, note = load_privacy_patterns(base)
    if note == "missing":
        return 0, ["privacy: no privacy.toml at %s — nothing to scan" % path]
    if note == "no-tomllib":
        return 0, ["privacy: tomllib unavailable (needs Python 3.11+); scan skipped"]
    if note and note.startswith("parse-error"):
        return 1, ["privacy: cannot parse %s (%s)" % (path, note)]
    if note == "patterns-not-a-list":
        return 1, ["privacy: `patterns` in %s is not a list" % path]
    if not pats:
        return 0, ["privacy: no patterns configured in %s" % path]
    markers = [(p, compile_marker(p)) for p in pats]
    hits = []
    # Sweep the WHOLE global corpus dir, not just *.md: the SessionEnd journal
    # (journal.ndjson / journal.1.ndjson) records cwd + git branch verbatim into this
    # same shared dir, and branch names / work paths are exactly work-marker shaped. A
    # detective backstop that only globs *.md is blind to that leak, so anyone who
    # promotes/shares/backs-up ~/.claude/memory/ ships those markers unflagged.
    mdir = memory_dir(base)
    scan_files = sorted(
        glob.glob(os.path.join(mdir, "*.md"))
        + glob.glob(os.path.join(mdir, "*.ndjson"))
    )
    for f in scan_files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for pat, rx in markers:
            if rx.search(text):
                hits.append((f, pat))
    if hits:
        lines = ["privacy: FOUND %d work-marker hit(s) in the global corpus:" % len(hits)]
        lines += ["  %s  matches pattern  %r" % (f, pat) for f, pat in hits]
        return 1, lines
    return 0, ["privacy: clean — no work markers in the global corpus"]


def index_privacy_advisory(base=None):
    """A one-line warning (or []) that the sqlite index embeds project-memory bodies.
    The index sits in the shareable memory dir and stores every project memory's BODY
    verbatim — exactly the work-marker content the privacy boundary keeps out of that
    dir — but the pattern scan can't read binary sqlite, so this warns explicitly rather
    than let `doctor --privacy` imply the whole dir is safe to share (CONF49)."""
    db = db_path(base)
    if not os.path.exists(db):
        return []
    return ["privacy: NOTE %s embeds project-memory bodies verbatim; it is a local cache — "
            "do NOT share/back-up this dir publicly, or delete the index (mem.py rebuilds "
            "it) before you do" % db]


def cmd_doctor(args):
    # Must create the DB and exit 0 on a fresh, empty corpus.
    mdir = memory_dir()
    try:
        conn, mode = open_db()
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()
    except CorruptIndex:
        # Diagnose, never traceback: doctor's whole job is to report health.
        print("mode=corrupt")
        print("memory_dir=%s (writable=%s)"
              % (mdir, "yes" if os.access(mdir, os.W_OK) else "no"))
        print("db=%s" % db_path())
        print("index corrupt — the index file is unreadable; delete it or run "
              "`mem.py index --rebuild` to reconstruct it from the corpus")
        print("privacy_toml=%s"
              % ("present" if os.path.exists(privacy_path()) else "absent"))
        if args.privacy:
            code, lines = privacy_scan()   # scans corpus FILES, not the db — still valid
            for ln in lines + index_privacy_advisory():
                print(ln)
            return code or 1
        return 1
    writable = os.access(mdir, os.W_OK)
    ppath = privacy_path()
    print("mode=%s" % mode)
    print("memory_dir=%s (writable=%s)" % (mdir, "yes" if writable else "no"))
    print("db=%s" % db_path())
    print("indexed=%d" % total)
    print("privacy_toml=%s" % ("present" if os.path.exists(ppath) else "absent"))
    if args.privacy:
        code, lines = privacy_scan()
        for ln in lines + index_privacy_advisory():
            print(ln)
        return code
    return 0


# ---------------------------------------------------------------------------
# gc-scan — mechanical corpus-health candidates (proposals only; read-only)
# ---------------------------------------------------------------------------
def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _memory_age_days(created, verified, mtime):
    """Prefer verified, then created (ISO YYYY-MM-DD), else file mtime."""
    for val in (verified, created):
        if val:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(val))
            if m:
                try:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    return (date.today() - d).days
                except ValueError:
                    pass
    if mtime:
        return int((time.time() - mtime) / 86400)
    return None


def gc_scan(base=None):
    conn, mode = open_db(base, recreate_on_corrupt=True)
    run_index(conn, mode)  # refresh index (corpus files untouched — read-only w.r.t. corpus)
    rows = conn.execute(
        "SELECT id, path, scope, name, description, type, created, verified, mtime, body "
        "FROM memories"
    ).fetchall()
    conn.close()

    mems = [{
        "id": r[0], "path": r[1], "scope": r[2], "name": r[3], "description": r[4],
        "type": r[5], "created": r[6], "verified": r[7], "mtime": r[8], "body": r[9],
    } for r in rows]

    near_dupes, stale, relative_dates, same_topic = [], [], [], []

    # 1) near-duplicate name/description (normalized equality).
    # A memory with no frontmatter `name:` falls back to its filename basename
    # (parse_file), so every native per-project MEMORY.md shares the name "MEMORY".
    # Matching on a filename-fallback name produced N-choose-2 bogus "identical name"
    # pairs across unrelated projects (CONF50) — so only compare names that differ from
    # the filename slug. Tradeoff: an EXPLICIT `name: Auth` in auth.md reads as a fallback
    # and won't be flagged as an identical-name dup — but such a pair still surfaces via
    # same_topic_pairs (shared keywords), and gc-scan only PROPOSES, so under-proposing an
    # exact-name match is a safe degradation. Distinguishing declared-vs-fallback origin
    # would need a schema column + index migration, not worth it for an advisory tool.
    def declared_name(m):
        n = _norm(m["name"])
        return n if n and n != _norm(slug_of(m["path"])) else ""
    for i in range(len(mems)):
        for j in range(i + 1, len(mems)):
            a, b = mems[i], mems[j]
            if declared_name(a) and declared_name(a) == declared_name(b):
                near_dupes.append({"a": a["path"], "b": b["path"], "reason": "identical name"})
            elif _norm(a["description"]) and _norm(a["description"]) == _norm(b["description"]):
                near_dupes.append({"a": a["path"], "b": b["path"],
                                   "reason": "identical description"})

    # 2) stale (>90d) project memories.
    for m in mems:
        if m["scope"] != "project":
            continue
        age = _memory_age_days(m["created"], m["verified"], m["mtime"])
        if age is not None and age > STALE_DAYS:
            stale.append({"path": m["path"], "age_days": age, "scope": m["scope"]})

    # 3) relative-date offenders.
    for m in mems:
        found = REL_DATE.findall("%s\n%s" % (m["description"], m["body"]))
        if found:
            uniq = sorted({f.strip().lower() for f in found})
            relative_dates.append({"path": m["path"], "matches": uniq})

    # 4) same-topic pair candidates (>=2 shared significant keywords in name/description).
    kw = [(m, set(keywords("%s %s" % (m["name"], m["description"])))) for m in mems]
    for i in range(len(kw)):
        for j in range(i + 1, len(kw)):
            (ma, ka), (mb, kb) = kw[i], kw[j]
            shared = ka & kb
            if len(shared) >= 2:
                same_topic.append({"a": ma["path"], "b": mb["path"],
                                   "shared": sorted(shared)})

    return {
        "near_duplicates": near_dupes,
        "stale": stale,
        "relative_dates": relative_dates,
        "same_topic_pairs": same_topic,
    }


def cmd_gc_scan(args):
    report = gc_scan()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    total = sum(len(v) for v in report.values())
    print("gc-scan: %d candidate(s) (proposals only — nothing deleted)" % total)
    for path in report["near_duplicates"]:
        print("  near-dup: %s <-> %s (%s)" % (path["a"], path["b"], path["reason"]))
    for s in report["stale"]:
        print("  stale:    %s (%d days)" % (s["path"], s["age_days"]))
    for r in report["relative_dates"]:
        print("  rel-date: %s -> %s" % (r["path"], ", ".join(r["matches"])))
    for p in report["same_topic_pairs"]:
        print("  topic:    %s <-> %s (shared: %s)" % (p["a"], p["b"], ", ".join(p["shared"])))
    return 0


# ---------------------------------------------------------------------------
# arg dispatch
# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="mem.py",
        description="fable-mem: cross-project persistent-memory index (stdlib + sqlite3).",
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{index,search,show,stats,doctor,gc-scan}")

    pi = sub.add_parser("index", help="index the corpus (mtime-incremental; --rebuild for full)")
    pi.add_argument("--rebuild", action="store_true", help="drop and rebuild the whole index")
    pi.set_defaults(func=cmd_index)

    ps = sub.add_parser("search", help="keyword search the corpus")
    ps.add_argument("query", nargs="+", help="query terms")
    ps.add_argument("--scope", choices=("global", "project", "all"), default="all")
    ps.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_search)

    psh = sub.add_parser("show", help="print a memory by id")
    psh.add_argument("id", type=int)
    psh.set_defaults(func=cmd_show)

    pst = sub.add_parser("stats", help="per-scope counts + index mode")
    pst.set_defaults(func=cmd_stats)

    pd = sub.add_parser("doctor", help="report FTS mode + corpus health (--privacy scan)")
    pd.add_argument("--privacy", action="store_true", help="scan global corpus for work markers")
    pd.set_defaults(func=cmd_doctor)

    pg = sub.add_parser("gc-scan", help="mechanical corpus-health candidates (proposals only)")
    pg.add_argument("--json", action="store_true")
    pg.set_defaults(func=cmd_gc_scan)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
