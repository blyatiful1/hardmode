#!/usr/bin/env python3
"""PreToolUse memory privacy guard (fable-protocol, L3).

WHY THIS EXISTS
    The one boundary that must hold in a cross-project memory system is
    project -> global promotion: a "work marker" (internal ticket id, private
    hostname, client codename) must NEVER cross into the machine-wide global corpus
    at `$BASE/memory/`. Advisory SKILL.md text is not enough — under momentum the
    model promotes anyway. This hook makes the boundary DETERMINISTIC: on any
    Write/Edit whose target resolves under `$BASE/memory/`, it scans the
    PENDING content against the user's `privacy.toml` patterns and BLOCKS the write
    (exit 2 — the tool does NOT run) on any hit, BEFORE the marker can land. Writes
    outside the global corpus, and clean payloads, pass untouched.

    SCOPE (not a jail): this matches the Write/Edit tools only. A promotion
    done through Bash (`cp`/`mv`/`cat >> ~/.claude/memory/x.md`) or an interpreter
    (`python3 -c`) does NOT carry a `file_path`/`content` this hook can see, so it is
    not scanned at write time — the same interpreter-bypass class the kit's other
    guards document. `mem.py doctor --privacy` is the detective backstop that sweeps
    already-written content (now including the .ndjson journal) and catches those.

FAIL-OPEN GUARANTEE
    A guard that breaks sessions costs more than it saves. Every failure mode —
    malformed stdin, no `privacy.toml`, no `tomllib`, unparseable patterns, a bug in
    this file — ends in `sys.exit(0)` (allow). It only ever exits 2 on a POSITIVE
    match of configured content against configured patterns. If it cannot load
    patterns it cannot honestly block, so it allows.
"""
import json
import os
import re
import sys

PRIVACY_TOML = "privacy.toml"


def base_dir():
    return os.environ.get("CLAUDE_DIR") or os.path.expanduser("~/.claude")


def memory_dir(base):
    return os.path.join(base, "memory")


def privacy_path(base):
    return os.path.join(memory_dir(base), PRIVACY_TOML)


def resolve_target(file_path, cwd):
    """Resolve a tool file_path to a real absolute path (relative-to-cwd aware)."""
    if not file_path:
        return None
    fp = os.path.expanduser(str(file_path))
    if not os.path.isabs(fp):
        fp = os.path.join(cwd or os.getcwd(), fp)
    return os.path.realpath(fp)


def _fs_case_insensitive(path):
    """True if `path` lives on a case-insensitive filesystem (macOS APFS/HFS+ default,
    Windows). Probed precisely — a case-variant of an existing path resolving to the
    SAME file — so we case-fold ONLY where the fs actually would, never false-blocking a
    genuinely distinct `Memory/` sibling on a case-sensitive Linux fs. Overridable with
    FABLE_MEM_FS_CASE_INSENSITIVE=1/0 (test seam + manual escape hatch)."""
    forced = os.environ.get("FABLE_MEM_FS_CASE_INSENSITIVE")
    if forced is not None:
        return forced == "1"
    try:
        alt = path.upper() if path != path.upper() else path.lower()
        return (path != alt and os.path.exists(path) and os.path.exists(alt)
                and os.path.samefile(path, alt))
    except OSError:
        return False


def under_global_corpus(target, base):
    """True iff `target` is the global memory dir or a file within it. realpath on
    both sides so a symlinked corpus is compared by its true location. On a
    case-insensitive fs, `$BASE/Memory/leak.md` addresses the SAME dir as
    `$BASE/memory/` (which mem.py's *.md glob would then index), so the comparison
    case-folds there — otherwise a capitalized path would slip a marker past the guard."""
    if not target:
        return False
    corpus = os.path.realpath(memory_dir(base))
    a, b = target, corpus
    if _fs_case_insensitive(corpus):
        a, b = a.lower(), b.lower()
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False  # different drives / not comparable


def pending_text(tool_input):
    """Gather every chunk of content this write would introduce: Write.content and
    Edit.new_string. Also scans a batch `edits` list defensively (any future
    multi-edit-shaped payload), so a batched write can't slip a marker past the guard."""
    chunks = []
    if not isinstance(tool_input, dict):
        return chunks
    for key in ("content", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str):
            chunks.append(v)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                chunks.append(e["new_string"])
    return chunks


def compile_marker(pattern):
    """Work-marker glob -> unanchored regex, matching mem.py's semantics exactly:
    `*` matches a run of non-space chars, everything else is a literal substring."""
    parts = str(pattern).split("*")
    return re.compile(r"\S*".join(re.escape(p) for p in parts))


def load_patterns(base):
    """Return list of raw pattern strings, or [] if patterns can't be loaded
    (any of: missing file, no tomllib, parse error, wrong type) => guard allows."""
    path = privacy_path(base)
    if not os.path.exists(path):
        return []
    try:
        import tomllib
    except ImportError:
        return []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []
    pats = data.get("patterns")
    if not isinstance(pats, list):
        return []
    return [str(x) for x in pats if str(x).strip()]


def block(target, pattern):
    print(
        "MEMORY PRIVACY GUARD (automated): blocked — this write targets the machine-wide "
        "GLOBAL memory corpus (%s) but its pending content matches the work-marker pattern "
        "%r from privacy.toml. Work markers (internal ticket ids, private hostnames, client "
        "codenames) must never cross project -> global memory. Remove the marker, or write "
        "this to the project-scoped memory (`$BASE/projects/<repo>/memory/`) instead. If it "
        "genuinely belongs in the global corpus, the pattern in privacy.toml is the thing to "
        "reconsider — do not work around this guard on your own." % (target, pattern),
        file=sys.stderr,
    )
    return 2


def main():
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return 0
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    base = base_dir()
    target = resolve_target(tool_input.get("file_path"), data.get("cwd"))
    if not under_global_corpus(target, base):
        return 0  # write is outside the global corpus — not our concern

    chunks = pending_text(tool_input)
    if not chunks:
        return 0
    patterns = load_patterns(base)
    if not patterns:
        return 0  # nothing configured / can't load — allow (fail open)

    haystack = "\n".join(chunks)
    for pat in patterns:
        if compile_marker(pat).search(haystack):
            return block(target, pat)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open — never break a session over a hook bug
