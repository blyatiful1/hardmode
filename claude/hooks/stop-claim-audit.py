#!/usr/bin/env python3
"""Stop-hook claim-audit gate (fable-protocol).

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
    r"|tests? (?:are )?(?:pass|passing|green))\b",
    re.IGNORECASE,
)
# Strip clearly-negated claims ("not done yet", "hasn't been verified", "remains
# to be fixed") before matching, so honest in-progress reports don't trip the gate.
# Kept conservative: a false block costs one cheap audit pass; a false pass costs
# a shipped bug.
NEGATED = re.compile(
    r"\b(?:not|never|isn'?t|aren'?t|wasn'?t|haven'?t|hasn'?t|can'?t be|cannot be"
    r"|(?:needs?|remains?|still|yet) to be)"
    r"\s+(?:yet\s+|been\s+|fully\s+|actually\s+)*"
    r"(?:done|completed?|finished|verified|fixed|resolved|implemented)\b",
    re.IGNORECASE,
)
MODIFYING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Bash commands that plausibly write files: redirections (except to /dev/*),
# in-place editors, file movers. Conservative — read-only sessions stay untaxed.
BASH_WRITE = re.compile(
    r"(?<![0-9&])>>?\s*(?!&|/dev/(?:null|stdout|stderr)\b)\S"
    r"|(?:^|[|&;]\s*)(?:sed\s+(?:-\S+\s+)*-i|tee\s|patch\s|truncate\s"
    r"|(?:git\s+(?:apply|mv|rm|checkout|restore|stash))|mv\s|cp\s|rm\s)"
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


def makes_claim(text):
    return bool(CLAIM.search(NEGATED.sub("", text)))


def main():
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return 0  # already continuing because of this hook — let the session end
    last_text = data.get("last_assistant_message", "")
    modified = False
    with open(data["transcript_path"]) as f:
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
                    elif name == "Bash":
                        inp = block.get("input")
                        cmd = inp.get("command", "") if isinstance(inp, dict) else ""
                        if isinstance(cmd, str) and BASH_WRITE.search(cmd):
                            modified = True
            if texts and not data.get("last_assistant_message"):
                last_text = "\n".join(texts)  # fallback for CLIs without the payload field
    if modified and makes_claim(last_text):
        print(REASON, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break the session over a hook bug — fail open
