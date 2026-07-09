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
Run against the installed CLI (BASE-resolved — honors `CLAUDE_DIR`). On Windows, invoke `python` wherever a command below says `python3`:
- `python3 ~/.claude/cli/mem.py search "<keywords>"` — top hits (title + one-line description + path). Add `--json` for structured output, `--scope global` (or `project`) to isolate a scope.
- `python3 ~/.claude/cli/mem.py show <id>` — read one memory's full body.
- `python3 ~/.claude/cli/mem.py stats` — per-scope counts (sanity-check the corpus is indexed).
- `python3 ~/.claude/cli/mem.py doctor` — FTS mode + corpus health if search behaves oddly.

The UserPromptSubmit recall hook already surfaces the top few cross-project hits automatically; use these commands when you need to search deliberately, widen beyond the auto-surfaced 3, or read a full body.

## Banking and promotion
To bank a lesson, use the **postmortem** skill — it writes the memory and decides scope.
A memory stays project-local by default; promotion project→global happens ONLY on an explicit
decision with a one-line why-global. The deterministic gate is `pretool-mem-privacy-guard.py`,
which blocks a Write/Edit/MultiEdit into the corpus carrying a work-marker regardless of intent
— so the common promotion path is prevention-by-hook. It does not see Bash/interpreter writes
(`cat >>`, `python3 -c`); run `mem doctor --privacy` as the backstop before promoting.
