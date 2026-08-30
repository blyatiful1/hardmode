---
name: postmortem
description: Distill a finished piece of work into auto-memory — the surprising root cause, the dead-end approach, the environment quirk, the decision and its why. Use proactively at the end of a debugging saga, after abandoning an approach, when something took 3+ attempts, or when the user says "remember this" / "lessons learned".
---

# Postmortem → memory

Memory is the highest-leverage capability multiplier an agent has, and it only works if
lessons get banked while they're fresh. Run this at the end of hard work, not "later".

## What earns a memory (any one)
- A root cause that was NOT where the symptoms pointed.
- An approach that looked right and failed — with why, so it isn't retried.
- An environment/tooling quirk (version pin, broken default, platform gotcha).
- A decision the user made that constrains future work (and its why).
- A calibration anchor (how long X actually takes on this machine, what Y actually costs).

## What does NOT
- Anything derivable from the repo, git history, or CLAUDE.md.
- Session-local details (paths in scratchpad, one-off numbers).
- Raw logs. Memories are conclusions, not transcripts.

## Procedure
1. Write the lesson as ONE falsifiable sentence first. If you can't, it isn't a lesson yet.
2. Check the memory directory for an existing file that covers it — UPDATE that file instead of duplicating; DELETE memories the new lesson proves wrong (stale memory is worse than none).
3. Otherwise write `<slug>.md` in the auto-memory directory with frontmatter (`name`, one-line `description`, `metadata.type`: user/feedback/project/reference/**open-loop**), body with **Why:** and **How to apply:**, and `[[links]]` to related memories. Use `open-loop` for a question left unresolved so a later session can close it.
4. Add one pointer line to MEMORY.md. Keep that index under 200 lines — prune the stalest entry if you're at the cap.
5. **Register recall keywords** (memdb): `python3 ~/.claude/memdb/memdb.py add` or edit `~/.claude/memdb/keywords.json` so the stub injector can surface the memory on matching prompts. A memory without registered keywords is invisible to recall — it exists only for sessions that happen to read MEMORY.md's one-liner.
6. Convert relative dates to absolute (YYYY-MM-DD) — "yesterday" is meaningless next session.

## Hygiene (adaptive learner, not a hoarder)
- Conclusions only, and only falsifiable ones — if step 1's sentence can't be proven wrong, it isn't a lesson.
- Update, don't duplicate: one topic file per lesson; sharpen the existing one rather than adding a near-dup.
- Delete on refutation: when new evidence disproves a banked memory, remove it — a confidently-wrong memory is worse than none.

## Privacy
The `pretool-mem-privacy-guard.py` hook blocks a **Write/Edit** into a memory file whose
content hits a work-marker pattern (ticket ids, client codenames, private hostnames —
`~/.claude/memory/privacy.toml`). It matches those tools only, not Bash/interpreter
writes (`cat >>`, `python3 -c`) — so never route memory writes through the shell, and
keep privacy.toml's patterns real: an empty pattern list fails open.
