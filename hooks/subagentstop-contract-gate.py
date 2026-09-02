#!/usr/bin/env python3
"""SubagentStop contract gate (hardmode).

The kit's verification agents promise a machine-readable final message:
  verifier     VERDICT: CONFIRMED | REFUTED | PARTIAL  +  EVIDENCE:  +  GAPS:
  plan-critic  VERDICT: SOUND | NEEDS CHANGES | WRONG APPROACH  +  BLOCKERS: RISKS: SIMPLER:
  oracle       DIAGNOSIS:  CONFIDENCE: high|medium|low  ALTERNATIVES:  NEXT EXPERIMENT:

That promise lived in prose. On this build (verified 2.1.258) SubagentStop carries
`agent_type` (also the matcher key), `last_assistant_message` and the subagent's own
`agent_transcript_path`, and exit 2 makes the SUBAGENT continue with the stderr as
feedback. So the contract is now enforced: a non-conforming final message is sent
back once with the exact missing markers, and the agent re-emits it in shape.

One more rule that prose could not hold: a verifier whose VERDICT is CONFIRMED but
whose own transcript contains no executed command (no Bash tool_use) has re-reasoned,
not verified. It is sent back once to run the check or downgrade to PARTIAL with a
COULD NOT VERIFY line.

Bounded by stop_hook_active (never blocks the re-emission). Fails open on anything
unexpected — an unreadable transcript, an empty message, an unknown agent type.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import iter_jsonl, ledger, reconfigure_utf8  # noqa: E402

CONTRACTS = {
    "verifier": {
        "markers": ["VERDICT:", "EVIDENCE:", "GAPS:"],
        "enum": ("VERDICT", r"VERDICT:\s*(CONFIRMED|REFUTED|PARTIAL)\b"),
        "shape": "VERDICT: CONFIRMED | REFUTED | PARTIAL\nEVIDENCE: <commands run + decisive output>\nGAPS: <unverified/broken, or none>",
    },
    "plan-critic": {
        "markers": ["VERDICT:", "BLOCKERS:", "RISKS:", "SIMPLER:"],
        "enum": ("VERDICT", r"VERDICT:\s*(SOUND|NEEDS CHANGES|WRONG APPROACH)\b"),
        "shape": "VERDICT: SOUND | NEEDS CHANGES | WRONG APPROACH\nBLOCKERS: <numbered, with evidence, or none>\nRISKS: <...>\nSIMPLER: <cheaper path or no>",
    },
    "oracle": {
        "markers": ["DIAGNOSIS:", "CONFIDENCE:", "ALTERNATIVES:", "NEXT EXPERIMENT:"],
        "enum": ("CONFIDENCE", r"CONFIDENCE:\s*(high|medium|low)\b"),
        "shape": "DIAGNOSIS: <mechanism + reasoning chain>\nCONFIDENCE: high | medium | low\nALTERNATIVES: <ranked>\nNEXT EXPERIMENT: <exact command(s)>",
    },
}


def last_message_from(path):
    by_id, last_id = {}, None
    for e in iter_jsonl(path):
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        mid = msg.get("id")
        if mid:
            last_id = mid
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text":
                by_id.setdefault(mid, []).append(str(b.get("text", "")))
    return "\n".join(by_id.get(last_id, [])) if last_id else ""


def ran_a_command(path):
    for e in iter_jsonl(path):
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                return True
    return False


def normalize(text):
    """Markdown emphasis and case are not violations: `**VERDICT:** Confirmed` is the
    verdict the contract asks for. Strip *, _ and backticks; compare case-insensitively."""
    return re.sub(r"[*_`]+", "", text)


def problems(base, text, transcript):
    c = CONTRACTS[base]
    text = normalize(text)
    out = [f"missing {m}" for m in c["markers"] if not re.search(r"(?im)^\s*" + re.escape(m), text)
           and m not in text]
    name, pat = c["enum"]
    if name + ":" in text and not re.search(pat, text, re.IGNORECASE):
        out.append(f"{name}: must be one of the listed values")
    if base == "verifier" and re.search(r"VERDICT:\s*CONFIRMED\b", text, re.IGNORECASE) and transcript \
            and os.path.isfile(transcript) and not ran_a_command(transcript):
        out.append("VERDICT: CONFIRMED with NO command run in your own context — that is "
                   "re-reasoning, not verification; run the check that would fail if the "
                   "claim were false, or downgrade to PARTIAL with a COULD NOT VERIFY line")
    return out


def main():
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return 0
    agent = data.get("agent_type") or ""
    base = agent.split(":")[-1]
    if base not in CONTRACTS:
        return 0
    transcript = data.get("agent_transcript_path")
    text = data.get("last_assistant_message") or ""
    if not text and isinstance(transcript, str):
        text = last_message_from(transcript)
    if not text.strip():
        return 0
    found = problems(base, text, transcript if isinstance(transcript, str) else "")
    if not found:
        ledger(data, "subagent-contract", "pass", base)
        return 0
    print(
        f"AGENT CONTRACT GATE (automated, fires once): your final message as `{agent}` does not "
        f"follow the required structure — {'; '.join(found)}. Re-emit your COMPLETE final "
        f"answer in exactly this shape:\n{CONTRACTS[base]['shape']}",
        file=sys.stderr,
    )
    ledger(data, "subagent-contract", "block", f"{base}:{found[0][:50]}")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open
