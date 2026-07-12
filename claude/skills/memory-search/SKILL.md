---
name: memory-search
description: Search the machine-wide cross-project memory corpus before re-deriving a decision you may have already made in another repo. Use when the user references past work ("like we did before", "the approach from the other project", "didn't we already solve this"), when you're about to re-derive a non-obvious decision, or when a lesson from a different repo would change what you build. Not for facts already visible in the current repo, git history, or CLAUDE.md.
---

# Cross-project memory search

Native auto-memory (MEMORY.md) only remembers THIS repo. fable-mem adds a machine-wide
corpus of banked lessons from every project. You under-trigger it: a decision you're about
to re-derive from scratch may already be banked from another repo. Search first.

## When to search (any one)
- Before re-deriving a non-obvious decision — check whether you already made it elsewhere.
- The user references past work not in this repo ("like the other project", "as before", "we solved this once").
- A saga smells familiar — a tooling quirk, a dead-end approach, a version pin you may have hit before.
- Before promoting a lesson to global (see below) — confirm it isn't already banked.

## When NOT to search
- Trivial lookups, or anything derivable from the current repo, git history, or CLAUDE.md — grep the repo instead.
- Facts native MEMORY.md already auto-loaded for this project.
- Routine edits where no cross-project lesson could change the answer.

## Commands
The CLI lives at `$CLAUDE_DIR/cli/mem.py` (default `~/.claude/cli/mem.py`) and resolves
the corpus from `CLAUDE_DIR` — so under a custom `CLAUDE_DIR`, use that path, not the
`~/.claude` literal shown here. On Windows, invoke `python` wherever a command says `python3`:
- `python3 "${CLAUDE_DIR:-$HOME/.claude}/cli/mem.py" search "<keywords>"` — top hits (title + one-line description + path). Add `--json` for structured output, `--scope global` (or `project`) to isolate a scope.
- `... mem.py show <id>` — read one memory's full body.
- `... mem.py stats` — per-scope counts (sanity-check the corpus is indexed).
- `... mem.py doctor` — FTS mode + corpus health if search behaves oddly.

The UserPromptSubmit recall hook already surfaces the top few cross-project hits automatically; use these commands when you need to search deliberately, widen beyond the auto-surfaced 3, or read a full body.

## Banking and promotion
To bank a lesson or promote one project→global, use the **postmortem** skill — it is the
single source of truth for the write mechanics and the privacy-guard boundary. Search here
first (step above) to confirm the lesson isn't already banked before you promote. And run
`mem doctor --privacy` as an explicit backstop before promoting/sharing: the write-time
guard only covers `Write|Edit` and fails open, so an interpreter- or copy-based promotion
(`cat >>`, `python3 -c`, `cp`) lands unscanned until the corpus sweep catches it.
