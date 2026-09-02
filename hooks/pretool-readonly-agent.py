#!/usr/bin/env python3
"""PreToolUse read-only enforcement for hardmode's verification agents.

The `verifier`, `plan-critic`, `oracle` and `scout` agents are DOCUMENTED as
read-only: their independence is the whole value of a fresh-context check, and a
verifier that can edit the code it verifies is not independent. But `tools: Read,
Bash, Grep, Glob` is only a tool-availability list — Bash writes freely — and this
build ignores agent-scoped `hooks:` for plugin agents. What it DOES do (verified on
2.1.258) is put `agent_type` into every PreToolUse payload fired inside a subagent.
So this plugin-level hook makes the read-only claim true: for those agent types it
DENIES (exit 2) any Bash command that would modify the working tree, and any
Edit/Write/NotebookEdit call, and tells the agent to report COULD NOT VERIFY instead.

Allowed for read-only agents: anything that only reads; redirections and file ops
whose every target is under the session's scratchpad_dir, the temp dir, or /dev;
non-mutating git verbs; package installs into the environment (pip/uv/poetry, a bare
npm ci/install) — they do not touch the tree. Denied: redirects into the tree,
in-place editors, mv/cp/rm/touch/mkdir of tree paths, tree-mutating git verbs
(commit, add, checkout, restore, reset, clean, rebase, merge, push, stash, apply,
rm, mv, cherry-pick, revert, am), dependency additions (npm install <pkg>, cargo
add, yarn/pnpm add), and formatters/fixers.

Add agent types with HARDMODE_READONLY_AGENTS=a,b (bare or plugin-namespaced names
both match). Fails open on anything unexpected; every denial is in the ledger.
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import blank_quotes, ledger, reconfigure_utf8  # noqa: E402

DEFAULT_AGENTS = {"verifier", "plan-critic", "oracle", "scout"}
EDITING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

_REDIRECT = re.compile(r"(?<![0-9&<])>>?\s*(\S+)")
_WRITE_VERB = re.compile(
    r"(?:^|[|&;]\s*)(?:sudo\s+)?(?:"
    r"(?P<inplace>sed\s+(?:-\S+\s+)*-i|perl\s+(?:-\S+\s+)*-p?i)"
    r"|(?P<fileop>tee|patch|truncate|touch|mv|cp|rm|rmdir|mkdir|ln|install|shred|dd|chmod|chown)\s+(?P<args>[^|&;]*)"
    r"|(?P<git>git\s+(?:-C\s+\S+\s+)?(?:commit|add|checkout|restore|switch|reset|clean|rebase|merge|push|apply|rm|mv|cherry-pick|revert|am"
    r"|stash(?!\s+(?:list|show)\b)|worktree\s+(?:add|remove|prune|move)|submodule\s+(?:add|update|deinit)"
    r"|tag\s+(?!-l\b|--list\b)[^-\s]|tag\s+-[adf]\b|branch\s+(?:-[dDmMc]\b|--delete|--move|--copy))\b)"
    r"|(?P<fmt>(?:black|isort|autopep8|yapf|prettier|gofmt|goimports|rustfmt|clang-format|shfmt)\s|ruff\s+format|ruff\s+check\s.*--fix|eslint\s.*--fix|cargo\s+fmt|npm\s+run\s+(?:format|fmt|fix))"
    r"|(?P<deps>npm\s+(?:install|i|add|uninstall|update)\s+[^-\s]|yarn\s+(?:add|remove)\b|pnpm\s+(?:add|remove)\b|cargo\s+(?:add|remove)\b)"
    r"|(?P<find>find\s.*\s-(?:delete|exec\s+(?:rm|mv|cp|sed)\b))|(?P<xargs>xargs\s+(?:-\S+\s+)*(?:rm|mv|cp|sed)\b)"
    r")")


def readonly_agents():
    extra = {a.strip() for a in os.environ.get("HARDMODE_READONLY_AGENTS", "").split(",") if a.strip()}
    return DEFAULT_AGENTS | extra


def is_readonly_agent(agent_type):
    if not isinstance(agent_type, str) or not agent_type:
        return False
    bare = agent_type.split(":")[-1]
    return agent_type in readonly_agents() or bare in readonly_agents()


def scratch_roots(data):
    roots = []
    for r in (data.get("scratchpad_dir"), tempfile.gettempdir(), "/tmp", "/dev", "/proc"):
        if isinstance(r, str) and r:
            roots.append(os.path.normpath(r))
    return roots


def under_scratch(path, roots, cwd):
    p = path.strip("'\"`")
    if p.startswith("&"):
        return True                      # `>&2` — a descriptor, not a file
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(cwd or "", p)
    p = os.path.normpath(p)
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def offending(cmd, data):
    """The reason this command would modify the tree, or None."""
    qb = blank_quotes(cmd)
    roots = scratch_roots(data)
    cwd = data.get("cwd") or ""
    for target in _REDIRECT.findall(qb):
        if not under_scratch(target, roots, cwd):
            return f"redirect into the working tree ({target})"
    for m in _WRITE_VERB.finditer(qb):
        if m.group("inplace"):
            return "in-place edit"
        if m.group("fileop"):
            verb = m.group("fileop")
            args = [a for a in m.group("args").split() if not a.startswith("-")]
            if verb == "dd":
                args = [a[3:] for a in args if a.startswith("of=")] or ["(no of=)"]
            elif verb in ("cp", "mv", "ln", "install"):
                args = args[-1:]                     # only the destination is written
            elif verb == "patch":
                args = ["(patch target)"]
            if not args or not all(under_scratch(a, roots, cwd) for a in args):
                return f"{verb} on a working-tree path"
            continue
        if m.group("git"):
            return "tree-mutating git command"
        if m.group("fmt"):
            return "formatter/fixer rewrites files"
        if m.group("deps"):
            return "dependency change rewrites lockfiles"
        if m.group("find") or m.group("xargs"):
            return "bulk file mutation"
    return None


def deny(data, agent, why):
    print(
        f"READ-ONLY AGENT (automated): `{agent}` is an independent verification agent and "
        f"may not modify the working tree — this command would ({why}). Independence is "
        "the point: a checker that edits what it checks proves nothing. Read, run the "
        "canonical checks, write scratch files only under the session scratchpad dir "
        f"({data.get('scratchpad_dir') or tempfile.gettempdir()}). If verifying needs a "
        "change, report COULD NOT VERIFY: <what> — <why> instead of making it.",
        file=sys.stderr,
    )
    ledger(data, "readonly-agent", "deny", f"{agent}:{why[:60]}")
    return 2


def main():
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    agent = data.get("agent_type")
    if not is_readonly_agent(agent):
        return 0
    tool = data.get("tool_name")
    if tool in EDITING_TOOLS:
        return deny(data, agent, f"{tool} edits a file")
    if tool != "Bash":
        return 0
    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    flat = re.sub(r"\s+", " ", cmd.replace("\\\n", " "))
    why = offending(flat, data)
    if why:
        return deny(data, agent, why)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open
