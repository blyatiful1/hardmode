#!/usr/bin/env python3
"""PreToolUse destructive-command guard (hardmode).

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
    use --force-with-lease), and recursive rm aimed at a catastrophic target
    (/, ~, $HOME, drive roots, ., .., *) in ANY argument position — long-form
    GNU flags and the PowerShell spellings (Remove-Item/ri/del, -Recurse and
    its abbreviations) included — blocked regardless of tree state.

On native Windows the guard also receives the PowerShell tool (the Windows
snippets match `Bash|PowerShell`): git commands are shell-identical, and the
rm check recognizes the PowerShell deletion spellings above.

Escape hatch: after the USER explicitly approves the loss, re-run the command
prefixed with HARDMODE_DESTRUCTIVE_OK=1. The model must never self-approve.

Fails open on any error (not a git repo, git missing, malformed payload):
a guard that can break sessions would cost more than it saves.
"""
import json
import re
import subprocess
import sys

OVERRIDE = "HARDMODE_DESTRUCTIVE_OK=1"
# The override only counts as an actual env-assignment prefix at the START of a shell
# segment (after any other leading VAR=val assignments) — NOT merely mentioned anywhere
# (a commit message or echo that contains the string must not disable the guard). It is
# matched per segment against the quote-stripped view, so it exempts only the command it
# prefixes, never later segments after a ; | && separator.
OVERRIDE_SEGMENT = re.compile(r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*HARDMODE_DESTRUCTIVE_OK=1(?:\s|$)")


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_SINGLE = re.compile(r"'[^']*'")
# Command substitutions execute inside double quotes and unquoted, but NOT inside single
# quotes (there they are literal). A destructive command hidden in "$(...)" or `...` must
# stay visible to the checks; one in '$(...)' must not false-trip. Scanned recursively to
# a bounded depth (see _iter_command_slices); the regex itself captures the innermost
# parenthesis-free span, so nested substitutions surface across recursion passes.
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
    """Contents of ACTIVE `$(...)` / backtick command substitutions in a segment (the
    caller recurses, bounded). Pass a single-quote-blanked slice so literal '$(...)'
    is ignored."""
    return [a or b for a, b in _SUBST.findall(segment)]


_HEREDOC_START = re.compile(r"<<-?\s*(['\"])([A-Za-z_]\w*)\1")


def _blank_quoted_heredocs(s):
    """Length- and newline-preserving blanking of QUOTED-delimiter heredoc bodies
    (<<'EOF' ... EOF): those are pure literal data — no expansions execute inside —
    so a test file or doc written through one must not trip the guard on strings it
    merely CONTAINS (the kit's own test suite writes `rm -rf /` fixtures this way).
    Unquoted-delimiter heredocs are left visible: `$(...)` executes inside them.
    A missing terminator blanks to the end — which is also what the shell does."""
    out = s
    for m in list(_HEREDOC_START.finditer(s)):
        delim = m.group(2)
        line_end = out.find("\n", m.end())
        if line_end == -1:
            break
        t = re.compile(r"\n[ \t]*" + re.escape(delim) + r"[ \t]*(?=\n|$)").search(out, line_end)
        end = t.start() if t else len(out)
        body = out[line_end + 1:end]
        out = out[:line_end + 1] + re.sub(r"[^\n]", " ", body) + out[end:]
    return out


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
ALWAYS_DANGEROUS = [
    (re.compile(r"\bgit\b[^|;&]*\bstash\s+(?:drop|clear)\b"),
     "git stash drop/clear permanently discards stashed work"),
]

# Recursive rm aimed at a catastrophic target. Checked against the rm-target view
# (bare quoted targets preserved) and — unlike a single anchored regex — token by
# token, so EVERY argument is a candidate target: `rm -rf build/ /` (the classic
# stray-space typo) is exactly as blocked as `rm -rf /`. -f is irrelevant: rm -r
# deletes without prompting in non-interactive shells.
_RM_INVOCATION = re.compile(r"\b(?:rm|ri|del|erase|remove-item)\s+(.*)", re.IGNORECASE)
# The recursive-flag grammars of the two shells COLLIDE on spelling (bash `-Rf` vs
# PowerShell `-Force` both contain an r), so a single regex can't tell them apart
# without false positives. We know the shell from tool_name, so match per shell:
#   bash: a combined short flag (single dash + letters) containing r/R — -r,-R,-rf,
#         -rfvi,-Rfiv — or GNU --recursive. PowerShell words never appear here.
#   PowerShell: -Recurse and its unambiguous prefixes (-r … -recurse, the only
#         Remove-Item parameter starting with r), optional :$bool. -Force/-Filter
#         are NOT recursive.
_BASH_RECURSIVE = re.compile(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive")
_PS_RECURSIVE = re.compile(
    r"-r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?(?::\$?\w+)?|--recursive", re.IGNORECASE)
# Catastrophic targets: / /* ~ ~/* $HOME ${HOME} . .. * plus Windows spellings —
# drive roots (C:\ C:/ C:), $env:USERPROFILE, backslash separators. Each target may
# carry a trailing separator and an optional glob star (~/*, $HOME/*, ./*, C:\*),
# not just the / root — `rm -rf ~/*` wipes the home dir exactly like `rm -rf ~`.
_SEP_STAR = r"(?:[/\\]\*?)?"
_RM_CATASTROPHIC = re.compile(
    r"[\"']?(?:/\*?|~" + _SEP_STAR + r"|\$\{?HOME\}?" + _SEP_STAR
    + r"|\$env:USERPROFILE" + _SEP_STAR + r"|[a-z]:" + _SEP_STAR
    + r"|\.\.?" + _SEP_STAR + r"|\*)[\"']?$",
    re.IGNORECASE)


def _rm_catastrophic(rmseg, is_powershell):
    """True iff any rm/Remove-Item invocation in this segment slice carries a recursive
    flag and ANY of its targets is catastrophic. `--` ends option parsing (everything
    after is a target); parameter values (e.g. -Path C:\\) land in the target list.
    is_powershell selects the recursive-flag grammar (the two shells collide)."""
    recursive_flag = _PS_RECURSIVE if is_powershell else _BASH_RECURSIVE
    for m in _RM_INVOCATION.finditer(rmseg):
        recursive, opts_ended, targets = False, False, []
        for t in m.group(1).split():
            if not opts_ended and t == "--":
                opts_ended = True
            elif not opts_ended and len(t) > 1 and t[0] == "-":
                if recursive_flag.fullmatch(t):
                    recursive = True
            else:
                targets.append(t)
        if recursive and any(_RM_CATASTROPHIC.fullmatch(t) for t in targets):
            return True
    return False
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
    separators, and — recursively, to a bounded depth — the commands inside each ACTIVE
    command substitution (`"$(...)"` / backticks / unquoted `$(...)`; single-quoted ones
    are literal and skipped). `useg` is the quote-stripped view (for git/force/tree
    patterns), `rmseg` the rm-target view (genuine quoted targets kept). An
    override-approved top-level segment — and everything inside it — is skipped."""
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
    # Hook payloads are UTF-8 regardless of OS locale; on Windows Python <=3.14 the
    # default is cp1252, where multi-byte content would crash the read and fail the
    # guard open — silently disabling it exactly when a session gets interesting.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name")
    if tool_name not in ("Bash", "PowerShell"):
        return 0
    is_powershell = tool_name == "PowerShell"
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
    flat = _blank_quoted_heredocs(flat)

    # The override is a shell env-assignment prefix: it applies ONLY to the command it
    # prefixes, so it exempts only its own segment. Unconditional blocks (rm at a
    # catastrophic target, stash drop, force-push) fire immediately; tree-destroyers block
    # only when the working tree is dirty, so they are collected and checked once at the end.
    tree_reason = None
    for useg, rmseg in _iter_command_slices(flat):
        for pat, why in ALWAYS_DANGEROUS:
            if pat.search(useg):
                return block(why)
        if _rm_catastrophic(rmseg, is_powershell):
            return block("recursive rm aimed at /, ~, $HOME, a drive root, ., .. or * "
                         "is unrecoverable")
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
