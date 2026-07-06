#!/usr/bin/env python3
"""PreToolUse destructive-command guard (fable-protocol).

Long-horizon autonomous sessions are exactly where a reflexive `git reset --hard`
or `git checkout -- .` destroys hours of uncommitted work. This hook blocks
(exit 2 — the command does NOT run) the small set of genuinely unrecoverable
operations, in two tiers:

  * working-tree destroyers (reset --hard, checkout --/-f/. , restore,
    switch -f/--discard-changes, clean -f) — blocked ONLY when
    `git status --porcelain` shows uncommitted or untracked work to lose;
    on a clean tree they pass untouched.
  * always-dangerous ops — `git stash drop|clear` (discards saved work),
    bare force-push in either spelling (`--force`/`-f` or a `+refspec`;
    use --force-with-lease), and `rm -rf` aimed at catastrophic targets
    (/, ~, ., .., *) — blocked regardless of tree state.

Escape hatch: after the USER explicitly approves the loss, re-run the command
prefixed with FABLE_DESTRUCTIVE_OK=1. The model must never self-approve.

Fails open on any error (not a git repo, git missing, malformed payload):
a guard that can break sessions would cost more than it saves.
"""
import json
import re
import subprocess
import sys

OVERRIDE = "FABLE_DESTRUCTIVE_OK=1"

# (pattern, why) — matched per shell segment context via a whole-command regex;
# [^|;&]* keeps a match from spanning into the next piped/chained command.
TREE_DESTROYERS = [
    (re.compile(r"\bgit\b[^|;&]*\breset\b[^|;&]*--hard"),
     "git reset --hard discards ALL uncommitted changes"),
    (re.compile(r"\bgit\b[^|;&]*\bcheckout\b[^|;&]*(?:\s--(?:\s|$)|\s-f\b|\s\.(?:\s|$|;))"),
     "git checkout with --/-f/. overwrites uncommitted local modifications"),
    (re.compile(r"\bgit\b[^|;&]*\bclean\b[^|;&]*\s-[a-zA-Z]*f"),
     "git clean -f permanently deletes untracked files"),
    (re.compile(r"\bgit\b[^|;&]*\bswitch\b[^|;&]*(?:\s-f\b|\s--force\b|\s--discard-changes\b)"),
     "git switch -f/--discard-changes overwrites uncommitted local modifications"),
]
RESTORE = re.compile(r"\bgit\b[^|;&]*\brestore\b([^|;&]*)")
ALWAYS_DANGEROUS = [
    (re.compile(r"\bgit\b[^|;&]*\bstash\s+(?:drop|clear)\b"),
     "git stash drop/clear permanently discards stashed work"),
    # rm with a recursive flag (-r/-R, combined or separate; -f irrelevant — rm -r
    # deletes without prompting in non-interactive shells) aimed at a catastrophic
    # first target: / /* ~ ~/ $HOME . ./ .. ../ *
    (re.compile(r"\brm\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*(?:\s+-\S+)*"
                r"\s+(?:\"|')?(?:/(?:\*)?|~(?:/)?|\$HOME(?:/)?|\.\.?(?:/)?|\*)(?:\"|')?(?:\s|$|;)"),
     "recursive rm aimed at /, ~, ., .. or * is unrecoverable"),
]
# --force / -f, plus the refspec spelling of force (`git push origin +main`) —
# the leading + IS --force for that ref and evades a flag-only check.
FORCE_PUSH = re.compile(r"\bgit\b[^|;&]*\bpush\b[^|;&]*(?:--force\b|\s-f\b|\s\+[A-Za-z0-9_./:~^-])")
FORCE_WITH_LEASE = re.compile(r"--force-with-lease\b")


def dirty_paths(cwd):
    try:
        p = subprocess.run(["git", "status", "--porcelain"], cwd=cwd or None,
                           capture_output=True, text=True, timeout=5)
        if p.returncode != 0:
            return 0
        return len([ln for ln in p.stdout.splitlines() if ln.strip()])
    except Exception:
        return 0


def block(reason):
    print(
        f"DESTRUCTIVE COMMAND GUARD (automated): blocked — {reason}. "
        "Checkpoint first (`git stash push -u` or a WIP commit), or if the USER has "
        f"explicitly approved losing this work, re-run prefixed with {OVERRIDE} . "
        "Never approve the loss on your own.",
        file=sys.stderr,
    )
    return 2


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    flat = re.sub(r"\s+", " ", cmd)
    if OVERRIDE in flat:
        return 0
    # Git patterns match on a quote-stripped view so a commit message or echo
    # that merely MENTIONS "reset --hard" never trips the guard. The rm pattern
    # matches the raw command — its targets are often quoted.
    unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", " ", flat)

    for pat, why in ALWAYS_DANGEROUS:
        haystack = flat if why.startswith("recursive rm") else unquoted
        if pat.search(haystack):
            return block(why)
    if FORCE_PUSH.search(unquoted) and not FORCE_WITH_LEASE.search(unquoted):
        return block("bare force-push can destroy remote history; use --force-with-lease, "
                     "and only with user approval")

    tree_reason = None
    for pat, why in TREE_DESTROYERS:
        if pat.search(unquoted):
            tree_reason = why
            break
    if tree_reason is None:
        m = RESTORE.search(unquoted)
        if m:
            args = m.group(1)
            # `git restore --staged <path>` only unstages — safe. Anything that
            # touches the worktree discards local edits.
            if "--staged" not in args or "--worktree" in args or re.search(r"\s-W\b", args):
                tree_reason = "git restore discards uncommitted modifications to the given paths"
    if tree_reason:
        n = dirty_paths(data.get("cwd"))
        if n:
            return block(f"{tree_reason}, and git status currently shows {n} "
                         f"changed/untracked path(s) that would be lost")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open — a guard must never break the session
