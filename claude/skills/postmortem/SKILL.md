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
3. Otherwise write `<slug>.md` in the auto-memory directory with frontmatter (`name`, one-line `description`, `metadata.type`: user/feedback/project/reference), body with **Why:** and **How to apply:**, and `[[links]]` to related memories.
4. Add one pointer line to MEMORY.md. Keep that index under 200 lines — prune the stalest entry if you're at the cap.
5. Convert relative dates to absolute (YYYY-MM-DD) — "yesterday" is meaningless next session.
