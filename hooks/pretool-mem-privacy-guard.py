#!/usr/bin/env python3
"""PreToolUse memory privacy guard (hardmode).

WHY THIS EXISTS
    Memory is the one place a session writes for EVERY future session. Two things
    must never land there: secrets (keys, tokens) and "work markers" (internal
    ticket ids, private hostnames, client codenames) that must not cross from a
    project into the machine-wide corpus. Advisory skill text is not enough — under
    momentum the model banks the note anyway. This hook makes the boundary
    DETERMINISTIC: on a Write/Edit whose target resolves into a memory corpus, it
    scans the PENDING content against the configured patterns and BLOCKS the write
    (exit 2 — the tool does NOT run) on a hit, BEFORE the marker lands.

WHICH CORPORA (verified against Claude Code 2.1.258)
    * the native auto-memory tree: <memory root>/projects/<project>/memory/ where
      <memory root> is CLAUDE_CODE_REMOTE_MEMORY_DIR or the config dir
      (CLAUDE_CONFIG_DIR, default ~/.claude) — this is where MEMORY.md lives;
    * the legacy machine-wide corpus <config dir>/memory/ (an operator's own layer).

WHICH PATTERNS
    The first readable file wins: <config dir>/memory/privacy.toml (the operator's
    own markers), else the plugin's doctrine/privacy.toml (shipped with secret-shaped
    defaults such as private-key headers and API-token prefixes, so the guard is
    armed out of the box). Each pattern is a work-marker glob: `*` matches a run of
    non-space characters, everything else is a literal substring. Parsed with
    tomllib when available, else with a minimal reader for the `patterns = [...]`
    shape — no Python-version dependency.

SCOPE (not a jail): Write/Edit only. A write done through Bash (`cat >>`) carries no
content the hook can see; the read-only agent hook and doctrine cover that path.

FAIL-OPEN GUARANTEE
    Malformed stdin, no pattern file, unparseable patterns, any bug here — all end
    in exit 0 (allow). It only ever exits 2 on a POSITIVE match.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import config_dir, ledger, reconfigure_utf8  # noqa: E402

PRIVACY_TOML = "privacy.toml"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def memory_root():
    return os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR") or config_dir()


def resolve_target(file_path, cwd):
    if not file_path:
        return None
    fp = os.path.expanduser(str(file_path))
    if not os.path.isabs(fp):
        fp = os.path.join(cwd or os.getcwd(), fp)
    return os.path.realpath(fp)


def _fs_case_insensitive(path):
    forced = os.environ.get("HARDMODE_MEM_FS_CASE_INSENSITIVE")
    if forced is not None:
        return forced == "1"
    try:
        alt = path.upper() if path != path.upper() else path.lower()
        return (path != alt and os.path.exists(path) and os.path.exists(alt)
                and os.path.samefile(path, alt))
    except OSError:
        return False


def _under(target, root):
    a, b = target, root
    if _fs_case_insensitive(root):
        a, b = a.lower(), b.lower()
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def guarded_corpus(target):
    """('global'|'project', corpus dir) when target is inside a memory corpus."""
    if not target:
        return None
    legacy = os.path.realpath(os.path.join(config_dir(), "memory"))
    if _under(target, legacy):
        return "global", legacy
    projects = os.path.realpath(os.path.join(memory_root(), "projects"))
    if _under(target, projects):
        rel = os.path.relpath(target, projects).split(os.sep)
        if len(rel) >= 3 and rel[1] == "memory":
            return "project", os.path.join(projects, rel[0], "memory")
    return None


def pending_text(tool_input):
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
    parts = str(pattern).split("*")
    return re.compile(r"\S*".join(re.escape(p) for p in parts))


def _parse_patterns(raw):
    """tomllib if available; else the minimal `patterns = [ "..", ]` reader."""
    try:
        import tomllib
        data = tomllib.loads(raw)
        pats = data.get("patterns")
        return [str(x) for x in pats if str(x).strip()] if isinstance(pats, list) else []
    except ImportError:
        pass
    except Exception:
        return []
    m = re.search(r"^\s*patterns\s*=\s*\[(.*?)\]", raw, re.S | re.M)
    if not m:
        return []
    body = re.sub(r"#[^\n]*", "", m.group(1))
    return [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'', body) for s in s if s]


def pattern_files():
    yield os.path.join(config_dir(), "memory", PRIVACY_TOML)
    # The harness sets CLAUDE_PLUGIN_ROOT for plugin hooks; the module-relative root
    # covers a hook run straight from a checkout (tests, demo).
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or PLUGIN_ROOT
    yield os.path.join(root, "doctrine", PRIVACY_TOML)


def load_patterns():
    """(patterns, source path). The first readable file with a non-empty list wins."""
    for path in pattern_files():
        try:
            with open(path, encoding="utf-8") as f:
                pats = _parse_patterns(f.read())
        except OSError:
            continue
        if pats:
            return pats, path
    return [], None


def block(target, pattern, kind, source):
    print(
        "MEMORY PRIVACY GUARD (automated): blocked — this write targets the %s memory "
        "corpus (%s) but its pending content matches the privacy pattern %r (from %s). "
        "Secrets and work markers (keys, tokens, internal ticket ids, private hostnames, "
        "client codenames) must never be banked in memory. Remove the marker before "
        "writing; if it genuinely belongs there, the pattern list is what to reconsider — "
        "do not work around this guard." % (kind, target, pattern, source),
        file=sys.stderr,
    )
    return 2


def main():
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit", None):
        return 0
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    target = resolve_target(tool_input.get("file_path"), data.get("cwd"))
    hit = guarded_corpus(target)
    if not hit:
        return 0
    kind, _corpus = hit
    chunks = pending_text(tool_input)
    if not chunks:
        return 0
    patterns, source = load_patterns()
    if not patterns:
        ledger(data, "mem-privacy", "inert-no-patterns", kind)
        return 0
    haystack = "\n".join(chunks)
    for pat in patterns:
        if compile_marker(pat).search(haystack):
            ledger(data, "mem-privacy", "block", f"{kind}:{pat[:40]}")
            return block(target, pat, kind, source)
    ledger(data, "mem-privacy", "pass", kind)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open — never break a session over a hook bug
