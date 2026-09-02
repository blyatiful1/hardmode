---
name: postmortem
description: Distill a finished piece of work into auto-memory — the surprising root cause, the dead-end approach, the environment quirk, the decision and its why. Use proactively at the end of a debugging saga, after abandoning an approach, when something took 3+ attempts, or when the user says "remember this" / "lessons learned".
---

# Postmortem → memory

Memory is the highest-leverage capability multiplier an agent has, and it only works if
lessons get banked while they're fresh — in a place a future session will actually read.
Run this at the end of hard work, not "later".

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
- Secrets, tokens, internal ticket ids, private hostnames, client codenames — the
  privacy guard blocks them anyway.

## Procedure
0. **Find the corpus** (mechanical): `python3 "${CLAUDE_PLUGIN_ROOT}/tools/memcheck.py" --where`
   prints the auto-memory directory for this project, whether memory is enabled, the
   index size and every existing topic file with its description. If memory is
   DISABLED, state the lesson in your final message and say it was not banked — never
   write into a corpus nothing will read.
1. Write the lesson as ONE falsifiable sentence first. If you can't, it isn't a lesson yet.
2. **Check for an existing file** (mechanical): `memcheck.py --dupes "<that sentence>"`
   lists topic files that overlap — UPDATE that file instead of duplicating; DELETE
   memories the new lesson proves wrong (stale memory is worse than none).
3. Otherwise write `<slug>.md` in the corpus directory with frontmatter (`name`, one-line
   `description`, `metadata.type`: user/feedback/project/reference/**open-loop**), body
   with **Why:** and **How to apply:**, and `[[links]]` to related memories. Use
   `open-loop` for a question left unresolved so a later session can close it.
4. Add one pointer line to MEMORY.md — the INDEX LINE is the recall surface: a future
   session sees only that line and must know from it whether to open the file. Keep
   the index short; prune the stalest entry if it is growing past a screen.
5. Convert relative dates to absolute (YYYY-MM-DD) — "yesterday" is meaningless next session.

## Hygiene (adaptive learner, not a hoarder)
- Conclusions only, and only falsifiable ones — if step 1's sentence can't be proven wrong, it isn't a lesson.
- Update, don't duplicate: one topic file per lesson; sharpen the existing one rather than adding a near-dup.
- Delete on refutation: when new evidence disproves a banked memory, remove it — a confidently-wrong memory is worse than none.

## Privacy
The `pretool-mem-privacy-guard.py` hook blocks a **Write/Edit** into a memory corpus (the
native `projects/<slug>/memory/` tree and the legacy `~/.claude/memory/`) whose content
matches a pattern in `privacy.toml` — the shipped defaults catch private keys and API
tokens; your own work markers go in `<config dir>/memory/privacy.toml`
(`tools/doctor.py --init-privacy` seeds it). It matches those tools only, not Bash
writes (`cat >>`) — so never route memory writes through the shell. `memcheck.py
--privacy` sweeps the existing corpus for anything that slipped in earlier.
