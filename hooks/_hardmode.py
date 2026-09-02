#!/usr/bin/env python3
"""Shared helpers for the hardmode hooks (stdlib only, every function fails open).

Hooks are run as `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<hook>.py"`; each hook adds
its own directory to sys.path and imports this module. Nothing here ever raises into
a hook: a helper that cannot do its job returns a default and the hook proceeds.

Contracts this module encodes (verified against Claude Code 2.1.258):
  * the config dir override is CLAUDE_CONFIG_DIR (`CLAUDE_DIR` never existed in the
    harness; it is honoured only as a legacy fallback for old state dirs);
  * hook payloads carry `agent_id`/`agent_type` when the tool call happens inside a
    subagent, and share the parent's `session_id`;
  * every hook may append to a per-session firing ledger so "does the floor ever
    fire?" is a measured number, not an assumption (tools/stats.py reads it).
"""
import json
import os
import re
import time

LEDGER_ENV = "HARDMODE_LEDGER"
STATE_TTL_DAYS = 7


def reconfigure_utf8(*streams):
    """Payloads, transcripts and block reasons are UTF-8 regardless of OS locale."""
    for s in streams:
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def config_dir():
    return (os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_DIR")
            or os.path.expanduser("~/.claude"))


def state_dir(create=True):
    d = os.environ.get("HARDMODE_STATE_DIR") or os.path.join(config_dir(), "tmp", "hardmode")
    if create:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    return d


def slug(value, n=80):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value or "unknown"))[:n]


def session_slug(data):
    return slug(data.get("session_id") if isinstance(data, dict) else None)


def scope_slug(data):
    """Session slug plus the agent id when the event fired inside a subagent, so
    parallel agents never share (and contaminate) one another's state files."""
    s = session_slug(data)
    agent = data.get("agent_id") if isinstance(data, dict) else None
    return f"{s}-{slug(agent, 32)}" if agent else s


def prune_stale(d, ttl_days=STATE_TTL_DAYS):
    cutoff = time.time() - ttl_days * 86400
    try:
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.unlink(p)
            except OSError:
                pass
    except OSError:
        pass


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def write_json_atomic(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


class locked:
    """Advisory exclusive lock on <path>.lock (fcntl where available, else a no-op).
    Concurrency-safe tool calls run in parallel, so a read-modify-write of a state
    file needs it or increments get lost."""

    def __init__(self, path):
        self.path = path + ".lock"
        self.fd = None

    def __enter__(self):
        try:
            import fcntl
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except Exception:
            self.fd = None
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
        return False


def ledger(data, hook, outcome, detail=""):
    """Append one firing record to the per-session ledger. Never raises, never
    changes a hook's exit code. Disabled with HARDMODE_LEDGER=0. Records carry no
    command text or file content — only the hook, the outcome and a short detail."""
    try:
        if os.environ.get(LEDGER_ENV, "1") == "0":
            return
        d = state_dir()
        rec = {
            "ts": int(time.time()),
            "hook": hook,
            "event": (data.get("hook_event_name") if isinstance(data, dict) else None) or "",
            "outcome": outcome,
            "detail": str(detail)[:200],
            "agent": (data.get("agent_type") if isinstance(data, dict) else None) or "",
        }
        line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
        if len(line) > 3900:
            line = line[:3900] + b"\n"
        path = os.path.join(d, f"ledger-{session_slug(data)}.jsonl")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass


def iter_jsonl(path):
    """Yield the dict entries of a JSONL file, skipping junk lines; empty on error."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    yield e
    except OSError:
        return


def subagent_transcripts(transcript_path, limit=200):
    """Transcripts of the subagents spawned from a session: the harness keeps them
    under <transcript stem>/subagents/**/agent-*.jsonl (Agent-tool and Workflow-tool
    agents alike). Capped so a huge session cannot blow a hook's timeout."""
    out = []
    try:
        stem = transcript_path[:-6] if transcript_path.endswith(".jsonl") else transcript_path
        root = os.path.join(stem, "subagents")
        if not os.path.isdir(root):
            return out
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name.startswith("agent-") and name.endswith(".jsonl"):
                    out.append(os.path.join(dirpath, name))
                    if len(out) >= limit:
                        return out
    except OSError:
        pass
    return out


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def blank_quotes(s):
    """Length-preserving: every quoted span becomes same-length spaces, so a commit
    message that merely MENTIONS a dangerous command cannot trip a pattern."""
    return _QUOTED.sub(lambda m: " " * len(m.group()), s)


# Shell commands that plausibly write files. Deliberately broad — for "did the session
# modify files" over-inclusion is the safe direction. Redirections (except to /dev/*),
# in-place editors, file movers, formatters/fixers, generators, package installs and
# worktree-rewriting git verbs. Matched against the QUOTE-BLANKED command so a `>`
# inside an awk/grep argument is not a redirect.
SHELL_WRITE = re.compile(
    r"(?<![0-9&<])>>?\s*(?!&|/dev/(?:null|stdout|stderr)\b)\S"
    r"|(?:^|[|&;]\s*)(?:sudo\s+)?(?:"
    r"sed\s+(?:-\S+\s+)*-i|perl\s+(?:-\S+\s+)*-p?i|tee\s|patch\s|truncate\s|touch\s"
    r"|(?:git\s+(?:apply|mv|rm|checkout|restore|stash|reset|clean|merge|rebase|revert|cherry-pick|pull|am)\b)"
    r"|mv\s|cp\s|rm\s|rmdir\s|mkdir\s|ln\s|install\s|shred\s|dd\s"
    r"|(?:black|isort|autopep8|yapf|prettier|gofmt|goimports|rustfmt|clang-format|shfmt)\s"
    r"|ruff\s+(?:format|check\s.*--fix)|eslint\s.*--fix|cargo\s+fmt|npm\s+run\s+(?:format|fmt|fix)"
    r"|pip3?\s+(?:install|uninstall)|npm\s+(?:install|i|ci|uninstall|update)\b|yarn\s+(?:add|remove|install)\b"
    r"|pnpm\s+(?:add|remove|install)\b|cargo\s+(?:add|remove)\b|poetry\s+(?:add|remove|lock)\b|uv\s+(?:add|remove|sync|lock)\b"
    r"|find\s.*\s-(?:delete|exec\s+(?:rm|mv|cp|sed)\b)|xargs\s+(?:-\S+\s+)*(?:rm|mv|cp|sed)\b"
    r")"
)

# A recognised check/test runner. Used by the claim gate (did a check run after the last
# edit, and did it pass?) and the commit preflight (has the check gone green since the
# last edit?). Matched against the quote-blanked, whitespace-collapsed command.
TEST_RUNNER = re.compile(
    r"(?:^|[|&;]\s*|\s)(?:"
    r"(?:python3?|py)\s+-m\s+(?:pytest|unittest|tox|nox|ruff|mypy|pyright)\b"
    r"|(?:\S*/)?(?:pytest|py\.test|tox|nox|ruff|mypy|pyright|flake8|pylint|bandit)\b"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|check|lint|typecheck|type-check|build|ci|verify)\b"
    r"|(?:npx\s+|bunx\s+)?(?:jest|vitest|mocha|ava|tap|karma|cypress|playwright|eslint|tsc)\b"
    r"|go\s+(?:test|vet|build)\b|cargo\s+(?:test|check|clippy|build)\b"
    r"|make\s+(?:-\S+\s+)*(?:test|tests|check|ci|verify|lint|validate)\b"
    r"|ctest\b|mvn\s+(?:\S+\s+)*(?:test|verify)\b|gradle(?:w)?\s+(?:\S+\s+)*(?:test|check)\b"
    r"|rspec\b|phpunit\b|dotnet\s+test\b|mix\s+test\b|sbt\s+test\b|swift\s+test\b|bats\b"
    r"|(?:\./|\S*/)?(?:verify|check|test|ci|lint)\.(?:sh|py)\b"
    r")"
)

# Output that means a check FAILED even when the tool result is not flagged is_error
# (`pytest || true`, a wrapper script that swallows the exit code).
FAILURE_OUTPUT = re.compile(
    r"\b[1-9]\d*\s+(?:failed|failing|errors?)\b|^FAILED\b|\bFAIL:|\bnpm ERR!|\berror TS\d+"
    r"|\bTests?:\s+\d+\s+failed|\b(?:build|check|tests?)\s+failed\b|\bpanicked at\b",
    re.IGNORECASE | re.MULTILINE,
)


def looks_like_test_run(cmd):
    return bool(TEST_RUNNER.search(blank_quotes(cmd))) if isinstance(cmd, str) else False


def looks_like_write(cmd):
    return bool(SHELL_WRITE.search(blank_quotes(cmd))) if isinstance(cmd, str) else False
