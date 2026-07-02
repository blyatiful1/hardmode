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
MODIFYING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

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


def main():
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return 0  # already continuing because of this hook — let the session end
    last_text = data.get("last_assistant_message", "")
    modified = False
    try:
        with open(data["transcript_path"]) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                texts = []
                for block in entry.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use" and block.get("name") in MODIFYING_TOOLS:
                        modified = True
                if texts and not data.get("last_assistant_message"):
                    last_text = "\n".join(texts)  # fallback for CLIs without the payload field
    except (OSError, KeyError):
        return 0  # never break the session over a hook error
    if modified and CLAIM.search(last_text):
        print(REASON, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
