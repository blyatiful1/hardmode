#!/usr/bin/env python3
"""PreToolUse destructive-command guard (hardmode).

Long-horizon autonomous sessions are exactly where a reflexive `git reset --hard`
or `rm -rf src/` destroys hours of uncommitted work. This hook blocks (exit 2 — the
command does NOT run) the small set of genuinely unrecoverable operations, in tiers:

  * working-tree destroyers — reset --hard, checkout --/-f/--force/./.., restore
    (worktree), switch -f/--force/--discard-changes, clean -f/--force — blocked ONLY
    when `git status --porcelain` shows uncommitted or untracked work to lose. When
    the command names explicit paths (`git checkout -- a.py`, `git restore src/`)
    only those paths are judged, so a scoped checkout of an unmodified file passes
    even on an otherwise-dirty tree. Dirtiness is judged in every directory the
    command names — the harness cwd, a `cd <dir>` target, `git -C <dir>` —
    so `cd repo && git reset --hard` from a clean cwd is still caught.
  * recursive rm of a directory that HOLDS UNCOMMITTED WORK (`rm -rf src/` with a
    modified file under src/) — blocked when git reports changed/untracked paths
    under the target; ignored build dirs (`node_modules`, `build/`) pass. `rm -rf
    .git`, the repository root, or its git dir are blocked unconditionally.
  * always-dangerous ops — `git stash drop|clear`, bare force-push in any spelling
    (`--force`, `-f`, combined `-uf`, a `+refspec`; use --force-with-lease), remote
    branch deletion (`push --delete`, `push origin :branch`), `reflog expire
    --expire=now`, `gc --prune=now`, `update-ref -d`, `worktree remove --force`,
    `shred`, and recursive rm / `find -delete` aimed at a catastrophic target (/,
    ~, $HOME, ., .., *, a whole system dir like /usr or /etc, the literal home dir)
    in ANY argument position — blocked regardless of tree state.
  * `git branch -D <name>` — blocked only when <name> is not merged anywhere.

Shell awareness: quoted strings and comments are blanked (a commit message that
MENTIONS `reset --hard` is fine), `$(...)`/backtick substitutions and `bash -c`/
`eval` payloads are scanned (through `sudo`/`env`/`timeout` launchers and absolute
interpreter paths), quoted-delimiter heredocs are literal data UNLESS they feed a
shell (`bash <<'EOF'`), and simple `VAR=value` assignments in the same command are
resolved before rm targets are judged (`T=/ && rm -rf $T`).

Escape hatch: after the USER explicitly approves the loss, re-run the command
prefixed with HARDMODE_DESTRUCTIVE_OK=1. The model must never self-approve.

Fails open on any error (not a git repo, git missing, malformed payload): a guard
that could break sessions would cost more than it saves. Every decision is written
to the firing ledger (tools/stats.py) so the guard's usefulness is measured.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import blank_quotes, ledger, normalize_cmd, reconfigure_utf8  # noqa: E402

OVERRIDE = "HARDMODE_DESTRUCTIVE_OK=1"
GIT_TIMEOUT = 3          # per call
GIT_BUDGET = 7.0         # total seconds of git across the hook (10s hook timeout)
MAX_DIRS = 3


def _home():
    try:
        h = os.path.expanduser("~")
        return h.rstrip("/") if h and h != "~" else None
    except Exception:
        return None


_HOME = _home()
_CATASTROPHIC_ABS = {
    "/usr", "/etc", "/var", "/bin", "/sbin", "/lib", "/lib32", "/lib64",
    "/boot", "/opt", "/srv", "/root", "/home", "/sys", "/proc", "/dev", "/run",
}
OVERRIDE_SEGMENT = re.compile(r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*HARDMODE_DESTRUCTIVE_OK=1(?:\s|$)")

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_SINGLE = re.compile(r"'[^']*'")
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
QUOTE_MARK = "\x01"   # stands in for a quote char in the rm view; stripped at tokenization


def _blank(s):
    return " " * len(s)


def _blank_single_quotes(s):
    return _SINGLE.sub(lambda m: _blank(m.group()), s)


def _rm_view(s):
    """Length-preserving view for the rm check: a quoted span holding a BARE target
    (`rm -rf "$DIR"/*`, `rm -rf "."`) keeps its content with the quote characters
    replaced by a marker (so the shell word stays ONE token), while a quoted span
    containing whitespace (a commit message that says `rm -rf /`) is blanked."""
    def repl(m):
        inner = m.group()[1:-1]
        if inner and not re.search(r"\s", inner):
            return QUOTE_MARK + inner + QUOTE_MARK
        return _blank(m.group())
    return _QUOTED.sub(repl, s)


def _blank_comments(flat):
    """Length-preserving blanking of `#`-to-end-of-line comments. bash treats `#` as a
    comment only at the start of a word, and never inside quotes — so the positions
    are found on the quote-blanked view and blanked in the raw string."""
    qb = blank_quotes(flat)
    out = list(flat)
    for m in re.finditer(r"(?:^|(?<=\s))#[^\n]*", qb):
        for i in range(m.start(), m.end()):
            out[i] = " "
    return "".join(out)


_HEREDOC_START = re.compile(r"<<-?\s*(?:(['\"])([A-Za-z_]\w*)\1|([A-Za-z_]\w*))")
_SHELL_WORD = r"(?:/\S*/)?(?:bash|sh|zsh|dash|ksh)"
_HEREDOC_TO_SHELL_BEFORE = re.compile(
    r"(?:^|[;|&\n]\s*)(?:[A-Za-z_]\w*=\S*\s+)*(?:(?:sudo|doas|env|command|exec|nohup|nice)\s+)*"
    + _SHELL_WORD + r"\b(?:\s+-\S+)*\s*$")
_HEREDOC_TO_SHELL_AFTER = re.compile(r"\|\s*(?:sudo\s+)?" + _SHELL_WORD + r"\b")


def _quoted_spans(s):
    return [(m.start(), m.end()) for m in _QUOTED.finditer(s)]


def _blank_quoted_heredocs(flat):
    """Length- and newline-preserving blanking of heredoc BODIES. A quoted-delimiter
    heredoc (<<'EOF') is pure literal data; an unquoted one (<<EOF) is prose too, except
    that `$(...)`/backtick substitutions execute inside it — so its body is blanked
    EXCEPT for those substitution spans, which stay visible and are scanned as commands.
    (Before this, a runbook written with `cat <<EOF` that merely mentioned `git reset
    --hard` was blocked as if the command ran.) Exceptions that keep the guard honest:
    a heredoc that is the stdin of a shell (`bash <<'EOF'`, `cat <<EOF | sh`) is executed
    line by line, so its body stays fully visible; and a heredoc marker that sits INSIDE
    a quoted string is a mention, not a heredoc, so it cannot blank the rest."""
    out = flat
    qb = blank_quotes(flat)
    spans = _quoted_spans(flat)
    for m in list(_HEREDOC_START.finditer(flat)):
        if any(a < m.start() < b for a, b in spans):
            continue
        quoted = m.group(1) is not None
        delim = m.group(2) if quoted else m.group(3)
        line_start = flat.rfind("\n", 0, m.start()) + 1
        line_end = out.find("\n", m.end())
        if line_end == -1:
            break
        before = qb[line_start:m.start()]
        after = qb[m.end():line_end]
        if _HEREDOC_TO_SHELL_BEFORE.search(before) or _HEREDOC_TO_SHELL_AFTER.search(after):
            continue
        t = re.compile(r"\n[ \t]*" + re.escape(delim) + r"[ \t]*(?=\n|$)").search(out, line_end)
        end = t.start() if t else len(out)
        body = out[line_end + 1:end]
        blanked = re.sub(r"[^\n]", " ", body)
        if not quoted:
            # keep the substitutions (the only executable thing in an unquoted body)
            pieces = list(blanked)
            for sm in _SUBST.finditer(body):
                pieces[sm.start():sm.end()] = body[sm.start():sm.end()]
            blanked = "".join(pieces)
        out = out[:line_end + 1] + blanked + out[end:]
    return out


def _segments(s):
    spans, start = [], 0
    for m in re.finditer(r"(?<!\\)[;|&\n]+", s):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(s)))
    return spans


# ---- git patterns (matched per shell segment on the quote-blanked view) -------------
_G = r"\bgit\b[^|;&]*"
_FORCE_FLAG = r"(?:\s--force\b|\s-[a-zA-Z]*f[a-zA-Z]*\b)"   # -f, -qf, -fq, --force
TREE_DESTROYERS = [
    (re.compile(_G + r"\breset\b[^|;&]*(?:--hard|--merge)\b"),
     "git reset --hard/--merge discards uncommitted changes", "reset-hard"),
    (re.compile(_G + r"\bcheckout\b[^|;&]*(?:\s--(?:\s|$)|" + _FORCE_FLAG + r"|\s\.\.?/?(?:\s|$))"),
     "git checkout with --/-f/--force/./.. overwrites uncommitted local modifications", "checkout"),
    (re.compile(_G + r"\bclean\b[^|;&]*(?:\s-[a-zA-Z]*f[a-zA-Z]*\b|\s--force\b)"),
     "git clean -f/--force permanently deletes untracked files", "clean"),
    (re.compile(_G + r"\bswitch\b[^|;&]*(?:" + _FORCE_FLAG + r"|\s--discard-changes\b)"),
     "git switch -f/--force/--discard-changes overwrites uncommitted local modifications", "switch"),
]
CHECKOUT_PATHS = re.compile(_G + r"\bcheckout\b[^|;&]*?\s--\s([^|;&]+)")   # one \s: a quoted path is blank in this view
RESTORE = re.compile(_G + r"\brestore\b([^|;&]*)")
ALWAYS_DANGEROUS = [
    (re.compile(_G + r"\bstash\s+(?:drop|clear)\b"),
     "git stash drop/clear permanently discards stashed work", "stash-drop"),
    (re.compile(_G + r"\breflog\b[^|;&]*\bexpire\b[^|;&]*--expire(?:-unreachable)?=(?:now|all)\b"),
     "git reflog expire --expire=now destroys the reflog, the last recovery path after a bad reset", "reflog-expire"),
    (re.compile(_G + r"\bgc\b[^|;&]*--prune=(?:now|all)\b"),
     "git gc --prune=now permanently deletes unreachable objects (no recovery of dropped commits)", "gc-prune"),
    (re.compile(_G + r"\bupdate-ref\b[^|;&]*\s-d\b"),
     "git update-ref -d deletes a ref outside git's safety checks", "update-ref"),
    (re.compile(_G + r"\bworktree\s+remove\b[^|;&]*(?:\s--force\b|\s-f\b)"),
     "git worktree remove --force discards uncommitted work in that worktree", "worktree-remove"),
    (re.compile(_G + r"\bpush\b[^|;&]*(?:\s--delete\b|\s-d\b|\s:[A-Za-z0-9_./-])"),
     "deleting a remote branch/tag cannot be undone from this machine", "push-delete"),
    (re.compile(r"(?:^|[\s;|&])(?:sudo\s+)?shred\b"),
     "shred overwrites file contents by design — unrecoverable", "shred"),
]
FORCE_PUSH = re.compile(_G + r"\bpush\b[^|;&]*(?:--force\b|\s-[a-zA-Z]*f[a-zA-Z]*\b|\s\+[A-Za-z0-9_./:~^-])")
FORCE_WITH_LEASE = re.compile(r"--force-with-lease(?:=\S*)?|--force-if-includes\b")
PUSH_DRY_RUN = re.compile(r"\s(?:--dry-run|-n)\b")
BRANCH_DELETE = re.compile(_G + r"\bbranch\b([^|;&]*(?:\s-D\b|\s--delete\s+--force\b|\s--force\s+--delete\b|\s-[a-zA-Z]*[dD][a-zA-Z]*\b[^|;&]*\s--force\b)[^|;&]*)")

# ---- rm / find ------------------------------------------------------------------------
_LAUNCHER = (r"(?:(?:/\S*/)?(?:sudo|doas|command|builtin|exec|nice|nohup|env|time)(?:\s+-\S+)*\s+"
             r"|(?:/\S*/)?timeout\s+(?:-\S+\s+)*\S+\s+|(?:/\S*/)?xargs\s+(?:-\S+\s+)*)")
_RM_INVOCATION = re.compile(
    r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*" + _LAUNCHER + r"*(?:/\S*/)?rm\s+(.*)")
_FIND_INVOCATION = re.compile(
    r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*" + _LAUNCHER + r"*(?:/\S*/)?find\s+(.*)")
_BASH_RECURSIVE = re.compile(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive")
_SEP_STAR = r"(?:/\*?)?"
_RM_CATASTROPHIC = re.compile(
    r"(?:/\*?|~" + _SEP_STAR + r"|\$\{?HOME\}?" + _SEP_STAR + r"|\.\.?" + _SEP_STAR + r"|\*)$")
_VAR_ASSIGN = re.compile(r"(?:^|[\s;&|])([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]*)")


def _abs_catastrophic(t, cwd=None):
    s = t.strip()
    if _HOME:
        if s.startswith("${HOME}"):
            s = _HOME + s[7:]
        elif s.startswith("$HOME"):
            s = _HOME + s[5:]
        elif s == "~" or s.startswith("~/"):
            s = _HOME + s[1:]
    if s.endswith("/*"):
        s = s[:-1]
    if not s.startswith("/"):
        return False
    norm = os.path.normpath(re.sub(r"^/+", "/", s))
    if norm == "/":
        return True
    return norm in _CATASTROPHIC_ABS or (_HOME is not None and norm == os.path.normpath(_HOME))


def _target_catastrophic(t):
    return bool(_RM_CATASTROPHIC.fullmatch(t)) or _abs_catastrophic(t)


def _assignments(flat):
    """Simple NAME=value assignments anywhere in the command, so a target assembled
    through a variable (`T=/ && rm -rf $T`) is judged by its value."""
    out = {}
    for m in _VAR_ASSIGN.finditer(flat):
        out[m.group(1)] = m.group(2).strip("\"'")
    return out


def _expand(token, env, cwd, git):
    """Resolve the expansions the guard can know about; unknown ones stay literal."""
    t = token
    for name, val in env.items():
        t = t.replace("${%s}" % name, val).replace("$" + name, val)
    if _HOME:
        t = t.replace("${HOME}", _HOME).replace("$HOME", _HOME)
    if cwd:
        t = t.replace("${PWD}", cwd).replace("$PWD", cwd).replace("$(pwd)", cwd)
    if "$(git rev-parse --show-toplevel)" in t:
        top = git.toplevel(cwd)
        if top:
            t = t.replace("$(git rev-parse --show-toplevel)", top)
    if "$(git rev-parse --git-dir)" in t:
        gd = git.git_dir(cwd)
        if gd:
            t = t.replace("$(git rev-parse --git-dir)", gd)
    return t


_KNOWN_SUBST = (
    ("$(git rev-parse --show-toplevel)", lambda cwd, git: git.toplevel(cwd)),
    ("`git rev-parse --show-toplevel`", lambda cwd, git: git.toplevel(cwd)),
    ("$(git rev-parse --git-dir)", lambda cwd, git: git.git_dir(cwd)),
    ("$(git rev-parse --absolute-git-dir)", lambda cwd, git: git.git_dir(cwd)),
    ("$(pwd)", lambda cwd, git: cwd),
    ("`pwd`", lambda cwd, git: cwd),
)


def _resolve_known_substitutions(flat, cwd, git):
    """Replace the handful of substitutions whose value the guard can compute
    (`$(git rev-parse --show-toplevel)`, `$(pwd)`) with that value, so an rm aimed at
    the repository through them is judged by the real path. Unknown substitutions
    stay literal (and are scanned as commands in their own right)."""
    for text, fn in _KNOWN_SUBST:
        if text in flat:
            val = fn(cwd, git)
            if val and " " not in val:
                flat = flat.replace(text, val)
    return flat


def _rm_targets(rmseg):
    """(recursive, targets) for an rm at command position in this segment slice, or
    None. `--` ends option parsing; every later token is a target."""
    m = _RM_INVOCATION.match(rmseg)
    if not m:
        return None
    recursive, opts_ended, targets = False, False, []
    for t in m.group(1).split():
        t = t.replace(QUOTE_MARK, "")
        if not t:
            continue
        if not opts_ended and t == "--":
            opts_ended = True
        elif not opts_ended and len(t) > 1 and t[0] == "-":
            if _BASH_RECURSIVE.fullmatch(t):
                recursive = True
        else:
            targets.append(t)
    return recursive, targets


_FIND_ROOT = re.compile(r"/\*?|~(?:/\*?)?|\$\{?HOME\}?(?:/\*?)?")


def _find_root_catastrophic(t):
    """`find .` is the everyday idiom, so unlike rm the relative forms (., .., *) are
    not catastrophic starts — only /, ~, $HOME and whole system dirs are."""
    return bool(_FIND_ROOT.fullmatch(t)) or _abs_catastrophic(t)


_PIPE_SPLIT = re.compile(r"(?<!\\)\|")


def _producer_targets(flat):
    """For every `... | xargs rm -r...` (or `| xargs -0 rm -rf`) stage whose rm carries no
    literal target, the targets come from the PRODUCER: a `find <starts>` (its start
    dirs), an `echo`/`printf` (its arguments), anything else -> unknown. Returned as
    (targets, known) pairs judged against catastrophic ROOTS only — a piped rm cannot
    be judged for uncommitted work, that needs literal paths."""
    out = []
    for chunk in re.split(r"(?<!\\)[;&\n]+", blank_quotes(flat)):
        stages = _PIPE_SPLIT.split(chunk)
        for i, st in enumerate(stages[1:], start=1):
            rm = _rm_targets(st)
            if not rm or rm[1]:
                continue
            prev = stages[i - 1].strip()
            fm = re.match(r"^(?:[A-Za-z_]\w*=\S*\s+)*(?:sudo\s+)?(?:/\S*/)?find\s+(.*)", prev)
            if not fm and not rm[0]:
                continue           # a non-recursive rm is only catastrophic when find walks for it
            if fm:
                starts = []
                for t in fm.group(1).split():
                    if t.startswith("-") or t in ("(", "!", ")"):
                        break
                    starts.append(t)
                out.append(starts or ["."])
            elif re.match(r"^(?:[A-Za-z_]\w*=\S*\s+)*(?:echo|printf)\s+(.*)", prev):
                out.append(re.match(r"^(?:[A-Za-z_]\w*=\S*\s+)*(?:echo|printf)\s+(.*)", prev).group(1).split())
            else:
                out.append(["."])
    return out


def _find_targets(rmseg):
    """Start directories of a `find` that deletes (-delete, -exec rm -r ...), else None."""
    m = _FIND_INVOCATION.match(rmseg)
    if not m:
        return None
    rest = m.group(1).replace(QUOTE_MARK, "")
    if not re.search(r"\s-delete\b|\s-exec\s+(?:\S*/)?rm\s+-[a-zA-Z]*[rR]", rest):
        return None
    starts = []
    for t in rest.split():
        if t.startswith("-") or t in ("(", "!", ")"):
            break
        starts.append(t)
    return starts or ["."]


# ---- directories the command operates on -------------------------------------------
_CD_TARGET = re.compile(r"\b(?:cd|pushd)\s+(\"[^\"]*\"|'[^']*'|[^\s;|&]+)")
_GIT_C_TARGET = re.compile(r"\bgit\b[^;|&]*?\s-C\s+(\"[^\"]*\"|'[^']*'|[^\s;|&]+)")
_GIT_WORKTREE = re.compile(r"--work-tree[=\s]+(\"[^\"]*\"|'[^']*'|[^\s;|&]+)")


def _resolve_dir(path, cwd):
    p = path.strip().strip("\"'")
    if _HOME:
        if p.startswith("~"):
            p = _HOME + p[1:]
        p = p.replace("${HOME}", _HOME).replace("$HOME", _HOME)
    if not os.path.isabs(p) and cwd:
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def _candidate_dirs(flat, cwd):
    dirs = [cwd] if cwd else []
    for pat in (_CD_TARGET, _GIT_C_TARGET, _GIT_WORKTREE):
        for m in pat.finditer(flat):
            d = _resolve_dir(m.group(1), cwd)
            if d not in dirs:
                dirs.append(d)
    return dirs[:MAX_DIRS]


class Git:
    """Bounded git probes: each call capped, and a total wall-clock budget so a hung
    repo can never starve the hook's 10s timeout. Every probe fails open."""

    def __init__(self):
        self.spent = 0.0
        self._cache = {}

    def run(self, args, cwd):
        key = (tuple(args), cwd)
        if key in self._cache:
            return self._cache[key]
        if self.spent > GIT_BUDGET:
            return (False, "")
        t0 = time.monotonic()
        try:
            p = subprocess.run(["git", *args], cwd=cwd or None, capture_output=True,
                               text=True, timeout=GIT_TIMEOUT)
            res = (p.returncode == 0, p.stdout)
        except Exception:
            res = (False, "")
        self.spent += time.monotonic() - t0
        self._cache[key] = res
        return res

    def dirty(self, cwd, paths=None):
        """Changed/untracked porcelain lines, optionally restricted to paths."""
        args = ["status", "--porcelain", "--untracked-files=normal"]
        if paths:
            args += ["--", *paths]
        ok, out = self.run(args, cwd)
        if not ok:
            return []
        return [ln for ln in out.splitlines() if ln.strip()]

    def toplevel(self, cwd):
        ok, out = self.run(["rev-parse", "--show-toplevel"], cwd)
        return os.path.normpath(out.strip()) if ok and out.strip() else None

    def git_dir(self, cwd):
        ok, out = self.run(["rev-parse", "--absolute-git-dir"], cwd)
        return os.path.normpath(out.strip()) if ok and out.strip() else None

    def unmerged(self, cwd):
        ok, out = self.run(["branch", "--format=%(refname:short)", "--no-merged=HEAD"], cwd)
        return {ln.strip() for ln in out.splitlines() if ln.strip()} if ok else set()


def _unmark(tokens):
    return [t.replace(QUOTE_MARK, "") for t in tokens if t.replace(QUOTE_MARK, "")]


def _args_from_view(pattern, useg, rmseg):
    """Match `pattern` on the quote-blanked view to DETECT, then read the argument text
    from the quote-preserving view at the same offsets — a quoted branch name or path
    is an argument, not empty space."""
    m = pattern.search(useg)
    if not m:
        return None
    raw = rmseg[m.start(1):m.end(1)] if m.lastindex else ""
    return _unmark(raw.split())


def block(data, rule, reason):
    print(
        f"DESTRUCTIVE COMMAND GUARD (automated): blocked — {reason}. "
        "Checkpoint first (`git stash push -u` or a WIP commit), or if the USER has "
        f"explicitly approved losing this work, re-run prefixed with {OVERRIDE} . "
        "Never approve the loss on your own.",
        file=sys.stderr,
    )
    ledger(data, "destructive-guard", "block", rule)
    return 2


_WRAPPER_START = re.compile(
    r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*" + _LAUNCHER + r"*(?:/\S*/)?(?:bash|sh|zsh|dash|ksh|eval)\b")
_WRAPPER_PAYLOAD = re.compile(r"(?:bash|sh|zsh|dash|ksh|eval)\b[^'\"]*?(['\"])(.*?)\1", re.S)


def _iter_command_slices(text, overridden, depth=0):
    """Yield (useg, rmseg) per command: top-level segments, the commands inside
    ACTIVE substitutions, and the payloads of shell wrappers. Override-approved
    top-level segments are skipped (and counted)."""
    qb = blank_quotes(text)
    rmv = _rm_view(text)
    sq = _blank_single_quotes(text)
    seg_view = _SUBST.sub(lambda m: _blank(m.group()), qb)
    for s, e in _segments(seg_view):
        useg = seg_view[s:e]
        if OVERRIDE_SEGMENT.search(useg):
            overridden.append(useg.strip())
            continue
        yield useg, rmv[s:e]
        if depth < 3:
            for a, b in _SUBST.findall(sq[s:e]):
                yield from _iter_command_slices(a or b, overridden, depth + 1)
            if _WRAPPER_START.match(useg):
                for m in _WRAPPER_PAYLOAD.finditer(text[s:e]):
                    yield from _iter_command_slices(m.group(2), overridden, depth + 1)


def main():
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    cwd = data.get("cwd")
    if not (isinstance(cwd, str) and os.path.isdir(cwd)):
        cwd = os.getcwd()          # the harness runs hooks in the project dir
    flat = normalize_cmd(cmd)
    flat = _blank_comments(flat)
    flat = _blank_quoted_heredocs(flat)
    env = _assignments(flat)
    git = Git()
    flat = _resolve_known_substitutions(flat, cwd, git)
    overridden = []

    tree = None            # (reason, rule, explicit paths or None)
    rm_checks = []         # resolved dirs whose dirty state decides
    branch_names = []
    for useg, rmseg in _iter_command_slices(flat, overridden):
        for pat, why, rule in ALWAYS_DANGEROUS:
            if pat.search(useg) and not (rule == "push-delete" and PUSH_DRY_RUN.search(useg)):
                return block(data, rule, why)
        rm = _rm_targets(rmseg)
        if rm:
            recursive, targets = rm
            targets = [_expand(t, env, cwd, git) for t in targets]
            if recursive and any(_target_catastrophic(t) for t in targets):
                return block(data, "rm-catastrophic",
                             "recursive rm aimed at /, ~, $HOME, a system dir, ., .. or * is unrecoverable")
            if recursive:
                for t in targets:
                    if "$(" in t or "`" in t or "$" in t:
                        continue  # unresolvable expansion — cannot judge, fail open
                    resolved = _resolve_dir(t, cwd)
                    base = os.path.basename(resolved.rstrip("/"))
                    probe = resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
                    real = os.path.realpath(resolved)
                    repo_dirs = {os.path.realpath(x) for x in (git.toplevel(cwd), git.git_dir(cwd),
                                                              git.toplevel(probe), git.git_dir(probe)) if x}
                    if base == ".git" or real in repo_dirs:
                        return block(data, "rm-repo",
                                     f"rm -r of {t} deletes the repository itself (all history and every recovery path)")
                    rm_checks.append((t, resolved))
        finds = _find_targets(rmseg)
        if finds and any(_find_root_catastrophic(_expand(t, env, cwd, git)) for t in finds):
            return block(data, "find-delete",
                         "find -delete / -exec rm -r starting at /, ~, $HOME or a system dir is unrecoverable")
        push_view = FORCE_WITH_LEASE.sub("", useg)
        if FORCE_PUSH.search(push_view) and not PUSH_DRY_RUN.search(useg):
            return block(data, "force-push",
                         "bare force-push can destroy remote history; use --force-with-lease, and only with user approval")
        if BRANCH_DELETE.search(useg):
            names = [t for t in (_args_from_view(BRANCH_DELETE, useg, rmseg) or []) if not t.startswith("-")]
            if not names or any("$" in n or "`" in n for n in names):
                return block(data, "branch-D",
                             "git branch -D with a branch name the guard cannot read (substitution/expansion) — "
                             "spell the branch out so it can be checked for unmerged commits")
            branch_names.extend(names)
        if tree is None:
            for pat, why, rule in TREE_DESTROYERS:
                if pat.search(useg):
                    paths = None
                    if rule == "checkout":
                        pm = _args_from_view(CHECKOUT_PATHS, useg, rmseg)
                        if pm:
                            paths = [p for p in pm if not p.startswith("-")] or None
                    tree = (why, rule, paths)
                    break
        if tree is None:
            m = RESTORE.search(useg)
            if m:
                args = m.group(1)
                staged_only = ("--staged" in args or re.search(r"\s-S\b", args)) and not (
                    "--worktree" in args or re.search(r"\s-W\b", args))
                if not staged_only:
                    paths = [p for p in (_args_from_view(RESTORE, useg, rmseg) or []) if not p.startswith("-")] or None
                    tree = ("git restore discards uncommitted modifications to the given paths",
                            "restore", paths)

    for targets in _producer_targets(flat):
        if any(_find_root_catastrophic(_expand(t, env, cwd, git)) for t in targets):
            return block(data, "xargs-rm",
                         "a recursive rm fed by find/xargs from /, ~, $HOME or a system dir is unrecoverable")
    dirs = _candidate_dirs(flat, cwd)
    if tree:
        why, rule, paths = tree
        for d in dirs:
            lines = git.dirty(d, paths)
            if lines:
                return block(data, rule,
                             f"{why}, and git status currently shows {len(lines)} changed/untracked "
                             f"path(s) that would be lost")
    for t, resolved in rm_checks:
        probe_cwd = resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
        lines = git.dirty(probe_cwd, [resolved]) if probe_cwd else []
        if lines:
            names = ", ".join(ln[3:].strip() for ln in lines[:5])
            return block(data, "rm-dirty",
                         f"rm -r {t} would delete {len(lines)} changed/untracked path(s) git still "
                         f"tracks as uncommitted work ({names})")
    if branch_names:
        for d in dirs:
            unmerged = git.unmerged(d)
            hit = [b for b in branch_names if b in unmerged]
            if hit:
                return block(data, "branch-D",
                             f"git branch -D {hit[0]} would delete commits reachable from no other ref")
    if overridden:
        ledger(data, "destructive-guard", "override", f"segments={len(overridden)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open — a guard must never break the session
