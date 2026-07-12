#!/usr/bin/env python3
"""PreToolUse destructive-command guard (fable-protocol).

Long-horizon autonomous sessions are exactly where a reflexive `git reset --hard`
or `git checkout -- .` destroys hours of uncommitted work. This hook blocks
(exit 2 — the command does NOT run) the small set of genuinely unrecoverable
operations, in two tiers:

  * working-tree destroyers (reset --hard, checkout --/-f/./.. , restore,
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
# The override only counts as an actual env-assignment prefix at the START of a shell
# segment (after any other leading VAR=val assignments) — NOT merely mentioned anywhere
# (a commit message or echo that contains the string must not disable the guard). It is
# matched per segment against the quote-stripped view, so it exempts only the command it
# prefixes, never later segments after a ; | && separator.
OVERRIDE_SEGMENT = re.compile(r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*FABLE_DESTRUCTIVE_OK=1(?:\s|$)")


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_SINGLE = re.compile(r"'[^']*'")
# Command substitutions execute inside double quotes and unquoted, but NOT inside single
# quotes (there they are literal). A destructive command hidden in "$(...)" or `...` must
# stay visible to the checks; one in '$(...)' must not false-trip. Single level of nesting.
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _blank(s):
    return " " * len(s)


def _blank_quotes(s):
    """Length-preserving: replace each quoted span with same-length spaces, so a commit
    message or echo that merely MENTIONS `reset --hard` can't trip the git checks while
    offsets stay aligned with the raw command."""
    return _QUOTED.sub(lambda m: _blank(m.group()), s)


def _blank_single_quotes(s):
    """Length-preserving blanking of SINGLE-quoted spans only — the view in which command
    substitutions are actually active (single quotes suppress them)."""
    return _SINGLE.sub(lambda m: _blank(m.group()), s)


def _rm_view(s):
    """Length-preserving view for the rm check: a quoted span holding a BARE target
    (`rm -rf "/"`, `rm -rf "$HOME"`) is un-quoted so the target stays matchable, but a
    quoted span with whitespace (a commit message that happens to say `rm -rf /`) is
    blanked — so the phrase-in-a-message case does not false-trip (only genuine quoted
    targets do)."""
    def repl(m):
        inner = m.group()[1:-1]
        if inner and not re.search(r"\s", inner):
            return " " + inner + " "   # len == len(inner)+2 == len(m.group())
        return " " * len(m.group())
    return _QUOTED.sub(repl, s)


def _subst_contents(segment):
    """Contents of ACTIVE `$(...)` / backtick command substitutions in a segment (one
    nesting level). Pass a single-quote-blanked slice so literal '$(...)' is ignored."""
    return [a or b for a, b in _SUBST.findall(segment)]


def _segments(s):
    """Yield (start, end) spans of s split on top-level shell separators ; | & and bare
    newlines. Operates on the length-preserving quote-stripped view, so separators inside
    quotes are already spaces and cannot cut a segment. A newline is a command separator
    exactly like `;` — collapsing it would let an override on one line suppress the next."""
    spans, start = [], 0
    for m in re.finditer(r"[;|&\n]+", s):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(s)))
    return spans

# (pattern, why) — matched per shell segment context via a whole-command regex;
# [^|;&]* keeps a match from spanning into the next piped/chained command.
TREE_DESTROYERS = [
    (re.compile(r"\bgit\b[^|;&]*\breset\b[^|;&]*--hard"),
     "git reset --hard discards ALL uncommitted changes"),
    (re.compile(r"\bgit\b[^|;&]*\bcheckout\b[^|;&]*(?:\s--(?:\s|$)|\s-f\b|\s\.\.?/?(?:\s|$|;))"),
     "git checkout with --/-f/./.. overwrites uncommitted local modifications"),
    (re.compile(r"\bgit\b[^|;&]*\bclean\b[^|;&]*\s-[a-zA-Z]*f"),
     "git clean -f permanently deletes untracked files"),
    (re.compile(r"\bgit\b[^|;&]*\bswitch\b[^|;&]*(?:\s-f\b|\s--force\b|\s--discard-changes\b)"),
     "git switch -f/--discard-changes overwrites uncommitted local modifications"),
]
RESTORE = re.compile(r"\bgit\b[^|;&]*\brestore\b([^|;&]*)")
# (pattern, why, raw_targets): raw_targets=True means match against the rm-target view
# (bare quoted targets preserved) instead of the fully quote-stripped view — an explicit
# flag, not a fragile substring check on `why`.
ALWAYS_DANGEROUS = [
    (re.compile(r"\bgit\b[^|;&]*\bstash\s+(?:drop|clear)\b"),
     "git stash drop/clear permanently discards stashed work", False),
    # rm with a recursive flag (-r/-R, combined or separate; -f irrelevant — rm -r
    # deletes without prompting in non-interactive shells) aimed at a catastrophic
    # first target: / /* ~ ~/ $HOME . ./ .. ../ *
    (re.compile(r"\brm\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*(?:\s+-\S+)*"
                r"\s+(?:\"|')?(?:/(?:\*)?|~(?:/)?|\$\{?HOME\}?(?:/)?|\.\.?(?:/)?|\*)(?:\"|')?(?:\s|$|;)"),
     "recursive rm aimed at /, ~, ., .. or * is unrecoverable", True),
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


def _iter_command_slices(text, depth=0):
    """Yield (useg, rmseg) for each command in `text`: top-level segments split on shell
    separators, and — one nesting level deep — the commands inside each ACTIVE command
    substitution (`"$(...)"` / backticks / unquoted `$(...)`; single-quoted ones are
    literal and skipped). `useg` is the quote-stripped view (for git/force/tree patterns),
    `rmseg` the rm-target view (genuine quoted targets kept). An override-approved
    top-level segment — and everything inside it — is skipped. Recursion is bounded."""
    qb = _blank_quotes(text)
    rmv = _rm_view(text)
    sq = _blank_single_quotes(text)          # view where substitutions are ACTIVE
    seg_view = _SUBST.sub(lambda m: _blank(m.group()), qb)  # blank substs so inner ; don't split
    for s, e in _segments(seg_view):
        useg = seg_view[s:e]
        if OVERRIDE_SEGMENT.search(useg):
            continue                          # user explicitly approved THIS command
        yield useg, rmv[s:e]
        if depth < 3:
            for content in _subst_contents(sq[s:e]):
                yield from _iter_command_slices(content, depth + 1)


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    # Honor line continuations (join `\<newline>`), then collapse only HORIZONTAL
    # whitespace so real newlines survive as command separators (a newline separates
    # commands exactly like `;`; collapsing it let an override on one line suppress the
    # next — see _segments).
    cmd = re.sub(r"\\\r?\n", " ", cmd).replace("\r\n", "\n").replace("\r", "\n")
    flat = re.sub(r"[^\S\n]+", " ", cmd).strip()

    # The override is a shell env-assignment prefix: it applies ONLY to the command it
    # prefixes, so it exempts only its own segment. Unconditional blocks (rm at a
    # catastrophic target, stash drop, force-push) fire immediately; tree-destroyers block
    # only when the working tree is dirty, so they are collected and checked once at the end.
    tree_reason = None
    for useg, rmseg in _iter_command_slices(flat):
        for pat, why, raw_targets in ALWAYS_DANGEROUS:
            if pat.search(rmseg if raw_targets else useg):
                return block(why)
        if FORCE_PUSH.search(useg) and not FORCE_WITH_LEASE.search(useg):
            return block("bare force-push can destroy remote history; use --force-with-lease, "
                         "and only with user approval")
        if tree_reason is None:
            for pat, why in TREE_DESTROYERS:
                if pat.search(useg):
                    tree_reason = why
                    break
        if tree_reason is None:
            m = RESTORE.search(useg)
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
