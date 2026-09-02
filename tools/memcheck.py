#!/usr/bin/env python3
"""hardmode memcheck — the mechanical half of the postmortem skill (stdlib only).

Auto-memory lives at <memory root>/projects/<slug>/memory/ (MEMORY.md + topic files),
where <memory root> is CLAUDE_CODE_REMOTE_MEMORY_DIR or the config dir and <slug> is
the working directory with every non-alphanumeric character replaced by '-'. This tool
answers the questions the skill used to leave to guesswork:

  --where            resolve the corpus for the cwd, say whether memory is enabled,
                     list the topic files with their descriptions and the index size
  --dupes "<text>"   list existing topic files that overlap with a lesson you are
                     about to bank (update those instead of duplicating)
  --privacy          sweep the corpus files for privacy.toml hits (exit 1 on any)

Usage: memcheck.py (--where | --dupes TEXT | --privacy) [--cwd DIR]
"""
import argparse
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hooks"))
from _hardmode import config_dir  # noqa: E402

STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "it", "this", "that", "with",
        "when", "not", "be", "as", "by", "at", "from", "was", "are", "use", "using"}


def memory_root():
    return os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR") or config_dir()


def slug(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd))


def memory_dir(cwd):
    return os.path.join(memory_root(), "projects", slug(cwd), "memory")


def frontmatter(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(4000)
    except OSError:
        return {}
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    out = {}
    if m:
        for ln in m.group(1).splitlines():
            if ":" in ln and not ln.startswith(" "):
                k, v = ln.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def topic_files(d):
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".md") and n != "MEMORY.md")
    except OSError:
        return []
    return [(n, frontmatter(os.path.join(d, n))) for n in names]


def where(cwd):
    d = memory_dir(cwd)
    disabled = os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    print(f"memory root:  {memory_root()}")
    print(f"project slug: {slug(cwd)}")
    print(f"corpus dir:   {d} ({'exists' if os.path.isdir(d) else 'not created yet'})")
    if disabled:
        print("auto-memory:  DISABLED via CLAUDE_CODE_DISABLE_AUTO_MEMORY — a banked lesson would not be read; state it in your final message instead")
    else:
        print("auto-memory:  enabled (no disable env var set)")
    index = os.path.join(d, "MEMORY.md")
    if os.path.isfile(index):
        with open(index, encoding="utf-8", errors="replace") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        print(f"MEMORY.md:    {len(lines)} non-empty line(s) (keep the index short — the harness truncates long ones)")
    else:
        print("MEMORY.md:    absent")
    files = topic_files(d)
    print(f"topic files:  {len(files)}")
    for n, fm in files:
        print(f"  - {n}: {fm.get('description', '(no description)')}")
    return 0


def words(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in STOP}


def dupes(cwd, text):
    d = memory_dir(cwd)
    probe = words(text)
    hits = []
    for n, fm in topic_files(d):
        have = words(n.replace("-", " ") + " " + fm.get("name", "") + " " + fm.get("description", ""))
        common = probe & have
        if len(common) >= 2:
            hits.append((len(common), n, sorted(common)))
    if not hits:
        print("no overlapping topic files — a new file is appropriate")
        return 0
    for score, n, common in sorted(hits, reverse=True):
        print(f"{n}: shares {score} word(s) {common} — UPDATE this file instead of adding a near-duplicate")
    return 0


def privacy(cwd):
    spec = importlib.util.spec_from_file_location("mem_guard", os.path.join(ROOT, "hooks", "pretool-mem-privacy-guard.py"))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    pats, source = guard.load_patterns()
    if not pats:
        print("no privacy patterns configured — nothing to sweep against")
        return 0
    markers = [(p, guard.compile_marker(p)) for p in pats]
    dirs = [memory_dir(cwd), os.path.join(config_dir(), "memory")]
    hits = 0
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if not n.endswith(".md"):
                continue
            path = os.path.join(d, n)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for i, ln in enumerate(f, 1):
                        for p, rx in markers:
                            if rx.search(ln):
                                hits += 1
                                print(f"{path}:{i}: matches {p!r}")
            except OSError:
                continue
    print(f"privacy sweep: {hits} hit(s) against {len(pats)} pattern(s) from {source}")
    return 1 if hits else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--where", action="store_true")
    g.add_argument("--dupes", metavar="TEXT")
    g.add_argument("--privacy", action="store_true")
    ap.add_argument("--cwd", default=os.getcwd())
    a = ap.parse_args(argv)
    if a.where:
        return where(a.cwd)
    if a.dupes is not None:
        return dupes(a.cwd, a.dupes)
    return privacy(a.cwd)


if __name__ == "__main__":
    sys.exit(main())
