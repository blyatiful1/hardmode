#!/usr/bin/env python3
"""Stop-hook claim-audit gate (hardmode) — evidence-based.

Blocks a stop (exit 2 + stderr) iff the final assistant message makes a completion
claim, the CURRENT TURN modified files, and the transcript holds no evidence that a
recognised check ran AND passed AFTER the last modification. It names the missing
evidence — the check that failed, the edit that came after the last green run, or
the absence of any check — instead of nagging once on every claim.

Evidence comes from the transcript itself (verified against Claude Code 2.1.258):
  * assistant `tool_use` blocks carry id + name + input; the following user entry's
    `tool_result` block carries tool_use_id + is_error, so every Edit/Write/Bash call
    has a known outcome — a failed or denied edit is not a modification, and a
    failing check is a failing check even when the model's summary says otherwise;
  * work delegated to subagents (Agent/Task/Workflow) lives in separate transcripts
    under <transcript stem>/subagents/**; they are scanned too, so "done" after
    delegated edits is audited exactly like direct edits;
  * the current turn starts at the last genuine user prompt (not isMeta, not a
    compaction summary), so a read-only follow-up question after audited work is
    never taxed;
  * `last_assistant_message` is sent by this build; the fallback reconstructs the
    last assistant MESSAGE from its `message.id` (one transcript entry per block).

Termination: the harness re-enters with stop_hook_active=true after a block. The
gate blocks again only when the evidence fingerprint changed (a new check ran and
failed, a new edit landed) and at most MAX_BLOCKS times per turn — never forever.
Uses the exit-2 + stderr blocking protocol. Fails open on anything unexpected.
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import (FAILURE_OUTPUT, iter_jsonl, ledger, looks_like_test_run,  # noqa: E402
                       looks_like_write, read_json, reconfigure_utf8, session_slug,
                       state_dir, subagent_transcripts, write_json_atomic)

CLAIM = re.compile(
    r"\b(done|complete|completed|finished|verified|fixed|resolved|implemented"
    r"|all (?:tests?|checks?|parts?) (?:pass|passing|green)"
    r"|tests? (?:are )?(?:pass|passing|green)"
    r"|(?:suite|build|ci|pipeline|lint(?:er)?|type ?check(?:er)?)\s+(?:is\s+|are\s+)?(?:green|passing|clean)"
    r"|all green|works now|no failures|ready to (?:merge|ship)|checks out"
    r"|fix(?:es)? (?:is|are) (?:applied|in place)"
    # German completion claims — an English-only gate is silently inert on half of a
    # German-speaking operator's completions (a false pass = a shipped bug).
    r"|fertig|erledigt|behoben|gel(?:ö|oe)st|implementiert|abgeschlossen|umgesetzt"
    r"|gefixt|gefixed|korrigiert|fertiggestellt"
    r"|funktioniert (?:jetzt|wieder)|l(?:ä|ae)uft (?:jetzt|wieder|durch)"
    r"|alle\s+tests?\s+(?:laufen|bestehen|sind\s+gr(?:ü|ue)n|gr(?:ü|ue)n)"
    r"|tests?\s+laufen\s+(?:\w+\s+){0,2}(?:gr(?:ü|ue)n|durch))\b",
    re.IGNORECASE,
)
# Strip clearly-negated claims and honest partial/failed reports before matching, so
# in-progress reports don't trip the gate. Conservative: a false block costs one
# cheap audit pass; a false pass costs a shipped bug.
_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|some|most|half|several|a\s+few|only\s+\d+)"
NEGATED = re.compile(
    r"\b(?:not|never|isn'?t|aren'?t|wasn'?t|haven'?t|hasn'?t|can'?t be|cannot be"
    r"|(?:needs?|remains?|still|yet) to be)"
    r"\s+(?:yet\s+|been\s+|fully\s+|actually\s+)*"
    r"(?:done|completed?|finished|verified|fixed|resolved|implemented)\b"
    r"|\b(?:unable|failed|couldn'?t|could not|didn'?t|did not|wasn'?t able|not able)"
    r"\s+(?:to\s+)?(?:fully\s+)?(?:complete|finish|fix|resolve|implement|verify)\w*"
    r"|\bwithout\s+(?:having\s+)?(?:completed|finished|fixed|verified)\b"
    r"|\b(?:not\s+all|no|none\s+of\s+the|" + _NUM + r"(?:\s+of\s+(?:the\s+)?\w+)?)"
    r"\s+(?:tests?|checks?|parts?)\s+(?:are\s+)?(?:pass(?:ing|es)?|green)\b"
    r"|\b(?:noch\s+)?nicht\s+(?:(?:ganz|wirklich|voll|vollst(?:ä|ae)ndig)\s+)?"
    r"(?:fertig|erledigt|behoben|gel(?:ö|oe)st|implementiert|abgeschlossen|umgesetzt|gefixt|korrigiert)\b"
    r"|\bnicht\s+alle\s+tests?\b|\bfunktioniert\s+(?:noch\s+)?nicht\b|\bl(?:ä|ae)uft\s+(?:noch\s+)?nicht\b",
    re.IGNORECASE,
)
# NOTE ON DELIBERATE OVER-BLOCKING: ordinary prose that reuses a claim word ("the
# hostname resolved to X", "the complete list") is accepted as a nuisance block —
# it costs one check run — rather than "fixed" by a strip that would also let a real
# "resolved by adding a null check" through.
MODIFYING_TOOLS = {"Edit", "Write", "NotebookEdit"}
DELEGATING_TOOLS = {"Agent", "Task", "Workflow"}
MAX_BLOCKS = 3

REASON = (
    "CLAIM AUDIT GATE (automated): your last message declares the work done/verified, "
    "but the transcript shows {reason}. Before finishing: (1) run the check that covers "
    "what you changed and read its result — a green run proves only what it ran; "
    "(2) re-read the ORIGINAL request: is EVERY part delivered, not just the parts you "
    "remember? (3) every 'done/passing/fixed/verified' claim must be backed by a tool "
    "result from THIS session. Fix what the check finds, then finish — or state "
    "honestly what is not done."
)
TEST_EDIT_ADDENDUM = (
    " ALSO: this turn edited test files. Confirm no test was weakened to force a pass "
    "— a loosened assertion, deleted case, widened tolerance, or added skip is not a "
    "fix. If a test's expectation was genuinely wrong, your final message must say so "
    "explicitly and justify the new expectation."
)
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)"
    r"|(^|/)test_[^/]+$"
    r"|_test\.[A-Za-z0-9]+$"
    r"|\.(test|spec)\.[A-Za-z0-9]+$",
    re.IGNORECASE,
)
_REDIRECT_TARGET = re.compile(r"(?<![0-9&<])>>?\s*(\S+)")


def is_test_path(p):
    return bool(TEST_PATH.search(p.replace("\\", "/"))) if isinstance(p, str) else False


def makes_claim(text):
    return bool(CLAIM.search(NEGATED.sub("", text or "")))


def bash_touches_tests(cmd):
    """True if a file-WRITING Bash command targets a test-looking path. A check run
    that merely logs its output (`pytest tests/test_x.py > out.log`) is not a test
    edit: for recognised runners only redirect targets count."""
    if looks_like_test_run(cmd):
        return any(is_test_path(t.strip("'\"`")) for t in _REDIRECT_TARGET.findall(cmd))
    for token in re.split(r"[\s;|&<>()]+", cmd):
        token = token.strip("'\"`").replace("\\", "/")
        if not token or re.fullmatch(r"\.?/?(tests?|__tests__|spec)/?", token, re.IGNORECASE):
            continue
        if TEST_PATH.search(token):
            return True
    return False


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def scan_transcript(path, is_sub=False):
    """Walk one transcript. Returns (events, prompt_timestamps, last_message_text):
    events are the tool calls in file order with their resolved outcome."""
    events, pending, prompts, by_id, last_id = [], {}, [], {}, None
    for entry in iter_jsonl(path):
        t = entry.get("type")
        ts = entry.get("timestamp") if isinstance(entry.get("timestamp"), str) else ""
        msg = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        content = msg.get("content")
        if t == "user":
            genuine = not entry.get("isMeta") and not entry.get("isCompactSummary")
            if isinstance(content, str):
                if genuine and content.strip():
                    prompts.append(ts)
                continue
            if not isinstance(content, list):
                continue
            has_text = has_result = False
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    has_result = True
                    ev = pending.pop(b.get("tool_use_id"), None)
                    if ev is not None:
                        ev["error"] = bool(b.get("is_error"))
                        ev["output"] = _text_of(b.get("content"))[:6000]
                elif b.get("type") == "text" and str(b.get("text", "")).strip():
                    has_text = True
            if genuine and has_text and not has_result:
                prompts.append(ts)
        elif t == "assistant":
            mid = msg.get("id")
            if mid:
                last_id = mid
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    by_id.setdefault(mid, []).append(str(b.get("text", "")))
                elif b.get("type") == "tool_use":
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    ev = {"ts": ts, "name": b.get("name"), "input": inp, "id": b.get("id"),
                          "error": None, "output": "", "sub": is_sub}
                    events.append(ev)
                    if ev["id"]:
                        pending[ev["id"]] = ev
    return events, prompts, "\n".join(by_id.get(last_id, [])) if last_id else ""


def classify(ev):
    """('mod' | 'run' | 'delegate' | None, detail)."""
    name, inp = ev["name"], ev["input"]
    if name in MODIFYING_TOOLS:
        return "mod", str(inp.get("file_path") or inp.get("notebook_path") or "")
    if name in DELEGATING_TOOLS:
        return "delegate", ""
    if name == "Bash":
        cmd = inp.get("command", "")
        cmd = cmd if isinstance(cmd, str) else ""
        if looks_like_test_run(cmd):
            return "run", cmd
        if looks_like_write(cmd):
            return "mod", cmd
    return None, ""


_SUMMARY = re.compile(r"\b[1-9]\d*\s+(?:failed|failing|errors?)\b", re.IGNORECASE)


def _decisive_line(output):
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    for line in lines:
        if _SUMMARY.search(line):
            return line[:160]
    for line in lines:
        if FAILURE_OUTPUT.search(line):
            return line[:160]
    return lines[-1][:160] if lines else "(no output captured)"


def _fp(*parts):
    return hashlib.sha1("\0".join(str(p) for p in parts).encode("utf-8", "replace")).hexdigest()[:16]


def decide(data):
    """Return (exit_code, message, ledger_outcome, ledger_detail)."""
    tp = data.get("transcript_path")
    if not isinstance(tp, str) or not os.path.isfile(tp):
        return 0, "", "pass", "no-transcript"
    events, prompts, last_text = scan_transcript(tp)
    text = data.get("last_assistant_message") or last_text
    if not makes_claim(text):
        return 0, "", "pass", "no-claim"

    boundary = prompts[-1] if prompts else ""

    def in_turn(e):
        return not boundary or not e["ts"] or e["ts"] >= boundary

    turn = [e for e in events if in_turn(e)]
    delegated = any(e["name"] in DELEGATING_TOOLS for e in turn)
    sub_files = subagent_transcripts(tp) if delegated else []
    for f in sub_files:
        sub_events, _, _ = scan_transcript(f, is_sub=True)
        turn.extend(e for e in sub_events if in_turn(e))
    turn.sort(key=lambda e: e["ts"] or "")

    kinds = [(classify(e), e) for e in turn]
    mods = [e for (k, _), e in kinds if k == "mod" and e["error"] is not True]
    runs = [e for (k, _), e in kinds if k == "run"]
    if not mods and not (delegated and not sub_files):
        return 0, "", "pass", "read-only"
    modified_tests = any(
        is_test_path(d) if e["name"] in MODIFYING_TOOLS else bash_touches_tests(d)
        for (k, d), e in kinds if k == "mod" and e in mods)
    last_mod_idx = max((turn.index(e) for e in mods), default=-1)
    after = [r for r in runs if turn.index(r) > last_mod_idx]

    if after:
        last = after[-1]
        cmd = last["input"].get("command", "")[:100]
        if last["error"] or (last["output"] and FAILURE_OUTPUT.search(last["output"])):
            code = "check-failed"
            reason = (f"the last check run after your final modification FAILED: `{cmd}` "
                      f"-> {_decisive_line(last['output'])}")
        elif modified_tests and not data.get("stop_hook_active"):
            code = "test-edit"
            reason = (f"`{cmd}` passed after your last change, but this turn edited test "
                      "files — the pass must not come from a weakened test")
        else:
            return 0, "", "pass", "evidence"
    elif runs:
        cmd = runs[-1]["input"].get("command", "")[:100]
        code = "stale-check"
        reason = (f"your last modification came AFTER the last check run (`{cmd}`); nothing "
                  "has been verified since")
    elif mods:
        code = "no-check"
        reason = ("no test/check runner was executed this turn (nothing matching pytest, "
                  "npm test, cargo test, go test, make check, verify.sh, ...)")
    else:
        code = "delegated-unknown"
        reason = ("work was delegated to subagents whose transcripts could not be read, "
                  "and no check ran in this turn")

    fp = _fp(code, boundary, mods[-1]["id"] if mods else "", after[-1]["id"] if after else "",
             len(turn))
    path = os.path.join(state_dir(), f"claim-gate-{session_slug(data)}.json")
    state = read_json(path, {})
    if state.get("turn") != boundary:
        state = {"turn": boundary, "blocks": 0, "fp": ""}
    if data.get("stop_hook_active") and (state.get("fp") == fp or state.get("blocks", 0) >= MAX_BLOCKS):
        return 0, "", "pass", f"budget:{code}"
    state.update({"fp": fp, "blocks": state.get("blocks", 0) + 1})
    write_json_atomic(path, state)
    msg = REASON.format(reason=reason) + (TEST_EDIT_ADDENDUM if modified_tests else "")
    return 2, msg, "block", code


def main():
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    code, msg, outcome, detail = decide(data)
    if msg:
        print(msg, file=sys.stderr)
    ledger(data, "claim-audit", outcome, detail)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never break the session over a hook bug — fail open
