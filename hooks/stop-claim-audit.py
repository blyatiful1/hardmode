#!/usr/bin/env python3
"""Stop-hook claim-audit gate (hardmode).

Blocks the FIRST stop of a session iff (a) the final assistant message makes a
completion claim and (b) the session modified files — then forces one audit pass.
Deterministic backstop for the documented Opus failure mode of declaring work
done without having run the check that actually covers the request.

Uses the exit-2 + stderr blocking protocol: the JSON {"decision":"block"} protocol
is silently fatal in `claude -p` print mode (verified empirically on 2.1.198).
"""
import json
import re
import sys

CLAIM = re.compile(
    r"\b(done|complete|completed|finished|verified|fixed|resolved|implemented"
    r"|all (?:tests?|checks?|parts?) (?:pass|passing|green)"
    r"|tests? (?:are )?(?:pass|passing|green)"
    # German completion claims — this user works in German, and an English-only gate
    # is silently inert on half their completions (a false pass = a shipped bug).
    r"|fertig|erledigt|behoben|gel(?:ö|oe)st|implementiert|abgeschlossen|umgesetzt"
    r"|alle\s+tests?\s+(?:laufen|bestehen|sind\s+gr(?:ü|ue)n|gr(?:ü|ue)n)"
    r"|tests?\s+laufen\s+(?:gr(?:ü|ue)n|durch))\b",
    re.IGNORECASE,
)
# Strip clearly-negated claims and clear non-claim uses of a claim word before
# matching, so honest in-progress reports and ordinary prose don't trip the gate.
# Kept conservative: a false block costs one cheap audit pass; a false pass costs
# a shipped bug.
NEGATED = re.compile(
    r"\b(?:not|never|isn'?t|aren'?t|wasn'?t|haven'?t|hasn'?t|can'?t be|cannot be"
    r"|(?:needs?|remains?|still|yet) to be)"
    r"\s+(?:yet\s+|been\s+|fully\s+|actually\s+)*"
    r"(?:done|completed?|finished|verified|fixed|resolved|implemented)\b"
    # The suite-claim forms need their own negations: "not all tests pass yet" /
    # "no checks are green" would otherwise still contain the positive CLAIM
    # substring ("all tests pass" / "checks are green") and false-block an
    # honest in-progress report.
    r"|\b(?:not\s+all|no|none\s+of\s+the)\s+(?:tests?|checks?|parts?)"
    r"\s+(?:are\s+)?(?:pass(?:ing|es)?|green)\b"
    # German negations: "noch nicht fertig", "nicht ganz behoben". Only a SHORT,
    # explicit intensifier may sit between "nicht" and the claim word — an
    # arbitrary-word gap would swallow a real claim ("nicht ganz trivial aber fertig").
    r"|\b(?:noch\s+)?nicht\s+(?:(?:ganz|wirklich|voll|vollst(?:ä|ae)ndig)\s+)?"
    r"(?:fertig|erledigt|behoben|gel(?:ö|oe)st|implementiert|abgeschlossen|umgesetzt)\b"
    r"|\bnicht\s+alle\s+tests?\b",
    re.IGNORECASE,
)
# NOTE ON DELIBERATE OVER-BLOCKING: the gate keeps its conservative bias — a false
# block costs one cheap audit pass, a false pass costs a shipped bug. So ordinary prose
# that reuses a claim word ("the hostname resolved to X", "the complete list below") is
# accepted as a nuisance block, not "fixed" by a strip that would also let a real
# "resolved by adding a null check" claim through. German word-order variants the
# negation can't see ("Fertig ist es noch nicht") likewise over-block on the safe side.
MODIFYING_TOOLS = {"Edit", "Write", "NotebookEdit"}
# Shell commands that plausibly write files: redirections (except to /dev/* and
# PowerShell's $null), in-place editors, file movers, and the PowerShell writing
# cmdlets — the Windows snippets wire the shell hooks to `Bash|PowerShell`, so a
# native-Windows session's primary shell is covered too. Conservative — read-only
# sessions stay untaxed. NOTE: the loop alarm uses a NARROWER LOOP_RESET (no bare
# redirects/tee) for its own reset decision; this gate keeps the broad definition
# because for "did the session modify files" over-inclusion is the safe direction.
BASH_WRITE = re.compile(
    r"(?<![0-9&])>>?\s*(?!&|\$null(?=[\s;|&]|$)|/dev/(?:null|stdout|stderr)\b)\S"
    r"|(?:^|[|&;]\s*)(?:sed\s+(?:-\S+\s+)*-i|tee\s|patch\s|truncate\s"
    r"|(?:git\s+(?:apply|mv|rm|checkout|restore|stash))|mv\s|cp\s|rm\s"
    r"|(?i:set-content|add-content|out-file|new-item|move-item|copy-item"
    r"|remove-item|rename-item)\b)"
)

REASON = (
    "CLAIM AUDIT GATE (automated, fires once per completion claim): your last message "
    "declares work done/verified after modifying files. Before finishing: "
    "(1) Re-read the ORIGINAL request — is EVERY part delivered, not just the parts you "
    "remember? (2) Every 'done/passing/fixed/verified' claim must be backed by a tool "
    "result from THIS session. A claim that a test suite passes counts only if the run "
    "actually collected every test the request scopes — a green run proves only what it "
    "ran. Run whatever check is missing now, fix what it finds, then finish. If every "
    "claim is already backed, restate the decisive evidence in one line each and finish."
)
TEST_EDIT_ADDENDUM = (
    " ALSO: this session edited test files. Confirm no test was weakened to force a "
    "pass — a loosened assertion, deleted case, widened tolerance, or added skip is "
    "not a fix. If a test's expectation was genuinely wrong, your final message must "
    "say so explicitly and justify the new expectation."
)
# Paths that look like tests: tests//test dirs, __tests__/, spec/, test_*.py,
# *_test.<ext>, *.test.<ext>, *.spec.<ext>. Conservative on purpose.
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)"
    r"|(^|/)test_[^/]+$"
    r"|_test\.[A-Za-z0-9]+$"
    r"|\.(test|spec)\.[A-Za-z0-9]+$",
    re.IGNORECASE,
)


def is_test_path(p):
    """TEST_PATH match with backslash paths normalized to forward slashes, so the
    directory/pytest heuristics fire on native-Windows file_path values (C:\\r\\tests\\
    test_x.py) that the Edit/Write tools emit — otherwise the gate's test-edit
    detection is silently inert on Windows (CONF1)."""
    return bool(TEST_PATH.search(p.replace("\\", "/"))) if isinstance(p, str) else False


def makes_claim(text):
    return bool(CLAIM.search(NEGATED.sub("", text)))


def bash_touches_tests(cmd):
    """True if a file-writing Bash command names a test-looking path anywhere.

    Coarse on purpose: `sed -i ... tests/test_x.py`, `echo ... > foo_test.go`,
    `mv a.py tests/b.py` all count. Read-only commands never reach here (the
    caller gates on BASH_WRITE first). A BARE test-dir token (`pytest tests/
    > out.log`) does not count — only tokens naming something inside one.
    """
    for token in re.split(r"[\s;|&<>()]+", cmd):
        token = token.strip("'\"`").replace("\\", "/")
        if not token or re.fullmatch(r"\.?/?(tests?|__tests__|spec)/?", token, re.IGNORECASE):
            continue
        if TEST_PATH.search(token):
            return True
    return False


def main():
    # Payload and transcript are UTF-8 regardless of OS locale; on Windows Python
    # <=3.14 the cp1252 default would crash on multi-byte content (an emoji in the
    # transcript) and fail the gate open — silently disabling it (CONF-UTF8).
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return 0  # already continuing because of this hook — let the session end
    last_text = data.get("last_assistant_message", "")
    modified = False
    modified_tests = False
    with open(data["transcript_path"], encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            content = entry.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            texts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    name = block.get("name")
                    if name in MODIFYING_TOOLS:
                        modified = True
                        inp = block.get("input")
                        fp = inp.get("file_path", "") if isinstance(inp, dict) else ""
                        if is_test_path(fp):
                            modified_tests = True
                    elif name in ("Bash", "PowerShell"):
                        inp = block.get("input")
                        cmd = inp.get("command", "") if isinstance(inp, dict) else ""
                        if isinstance(cmd, str) and BASH_WRITE.search(cmd):
                            modified = True
                            if bash_touches_tests(cmd):
                                modified_tests = True
            if texts and not data.get("last_assistant_message"):
                last_text = "\n".join(texts)  # fallback for CLIs without the payload field
    if modified and makes_claim(last_text):
        print(REASON + (TEST_EDIT_ADDENDUM if modified_tests else ""), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break the session over a hook bug — fail open
