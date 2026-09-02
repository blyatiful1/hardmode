# Unit tests for the Stop-hook claim-audit gate (evidence-based).
# Transcripts are built in the real 2.1.258 shape: assistant entries with message.id
# and tool_use blocks, user entries with tool_result blocks carrying is_error, ISO
# timestamps, isMeta on harness-injected turns, subagent transcripts under
# <stem>/subagents/**.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "stop-claim-audit.py"


class Transcript:
    def __init__(self, tmp_path, name="transcript"):
        self.path = tmp_path / f"{name}.jsonl"
        self.entries, self.n, self.ids = [], 0, 0

    def _ts(self):
        self.n += 1
        return f"2026-09-02T05:{self.n // 60:02d}:{self.n % 60:02d}.000Z"

    def prompt(self, text, meta=False, compact_summary=False):
        e = {"type": "user", "timestamp": self._ts(), "message": {"role": "user", "content": text}}
        if meta:
            e["isMeta"] = True
        if compact_summary:
            e["isCompactSummary"] = True
        self.entries.append(e)
        return self

    def text(self, text, mid=None):
        self.entries.append({"type": "assistant", "timestamp": self._ts(),
                             "message": {"id": mid or f"msg_{self.n}", "role": "assistant",
                                         "content": [{"type": "text", "text": text}]}})
        return self

    def tool(self, name, ok=True, output="", result=True, mid=None, **inp):
        self.ids += 1
        tid = f"toolu_{self.ids:04d}"
        self.entries.append({"type": "assistant", "timestamp": self._ts(),
                             "message": {"id": mid or f"msg_{self.n}", "role": "assistant",
                                         "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        if result:
            block = {"type": "tool_result", "tool_use_id": tid, "content": output}
            if not ok:
                block["is_error"] = True
            self.entries.append({"type": "user", "timestamp": self._ts(),
                                 "message": {"role": "user", "content": [block]}})
        return self

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in self.entries),
                             encoding="utf-8")
        return self.path


def run_hook(tmp_path, transcript, last_message=None, stop_hook_active=False, raw_stdin=None,
             session="s1", state_dir=None):
    payload = {"transcript_path": str(transcript), "stop_hook_active": stop_hook_active,
               "session_id": session, "hook_event_name": "Stop"}
    if last_message is not None:
        payload["last_assistant_message"] = last_message
    env = dict(os.environ, HARDMODE_STATE_DIR=str(state_dir or tmp_path / "state"))
    return subprocess.run([sys.executable, str(HOOK)],
                          input=raw_stdin if raw_stdin is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=env)


def edit_no_check(tmp_path, text="All done — tests pass and the fix is verified."):
    t = Transcript(tmp_path).prompt("fix the parser").tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
    return t.text(text).write()


# ---- the evidence decision ----

def test_claim_after_edit_with_no_check_blocks_and_says_why(tmp_path):
    r = run_hook(tmp_path, edit_no_check(tmp_path))
    assert r.returncode == 2
    assert "CLAIM AUDIT GATE" in r.stderr and "no test/check runner" in r.stderr


def test_green_check_after_last_edit_passes_silently(tmp_path):
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .tool("Bash", command="python3 -m pytest -q", output="12 passed in 0.4s")
         .text("Done — all tests pass."))
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_failing_check_after_last_edit_blocks_and_names_it(tmp_path):
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .tool("Bash", command="pytest -q", ok=False, output="FAILED tests/test_x.py::test_a\n1 failed, 11 passed")
         .text("All done — tests pass."))
    r = run_hook(tmp_path, t.write())
    assert r.returncode == 2
    assert "FAILED" in r.stderr and "pytest -q" in r.stderr and "1 failed, 11 passed" in r.stderr


def test_failure_visible_in_output_counts_even_without_is_error(tmp_path):
    # `pytest || true` masks the exit code; the output still says 3 failed.
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .tool("Bash", command="pytest -q || true", output="3 failed, 9 passed in 1.2s")
         .text("Fixed and verified."))
    r = run_hook(tmp_path, t.write())
    assert r.returncode == 2 and "3 failed" in r.stderr


def test_edit_after_last_green_check_blocks_as_stale(tmp_path):
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Bash", command="pytest -q", output="12 passed")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .text("Done, tests are green."))
    r = run_hook(tmp_path, t.write())
    assert r.returncode == 2 and "AFTER the last check run" in r.stderr


def test_no_block_without_modification(tmp_path):
    t = Transcript(tmp_path).prompt("what does x do?").tool("Read", file_path="x.py").text("Done — everything is verified.")
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_no_block_without_claim(tmp_path):
    t = Transcript(tmp_path).prompt("refactor").tool("Write", file_path="x.py", content="x").text("I refactored the parser; next I plan to add tests.")
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_failed_or_denied_edit_is_not_a_modification(tmp_path):
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Edit", ok=False, output="String to replace not found in file.", file_path="x.py", old_string="a", new_string="b")
         .text("I could not apply the change; the file is unchanged. Done for now — verified nothing changed."))
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_bash_write_counts_as_modification(tmp_path):
    t = Transcript(tmp_path).prompt("cfg").tool("Bash", command="echo hello > config.yaml", output="").text("Config fixed, all checks pass.")
    assert run_hook(tmp_path, t.write()).returncode == 2
    t = Transcript(tmp_path).prompt("cfg").tool("Bash", command="sed -i 's/a/b/' src/main.py", output="").text("Renamed everywhere — done.")
    assert run_hook(tmp_path, t.write()).returncode == 2
    t = Transcript(tmp_path).prompt("fmt").tool("Bash", command="black src/", output="reformatted 3 files").text("Formatting done.")
    assert run_hook(tmp_path, t.write()).returncode == 2


def test_readonly_bash_does_not_count(tmp_path):
    t = (Transcript(tmp_path).prompt("analyse")
         .tool("Bash", command="grep -rn 'foo' src/ | head -20", output="src/a.py:1:foo")
         .tool("Bash", command="pytest -q > /dev/null 2>&1", output="")
         .tool("Bash", command="awk '$3 > 100 {print}' access.log", output="")
         .text("Analysis complete: the bug is in parser.py (verified by reading the code)."))
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_check_with_log_redirect_is_a_run_not_a_test_edit(tmp_path):
    t = (Transcript(tmp_path).prompt("fix")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .tool("Bash", command="pytest tests/test_x.py -q > out.log 2>&1", output="")
         .text("All tests pass — done."))
    r = run_hook(tmp_path, t.write())
    assert r.returncode == 0


# ---- termination and turn scoping ----

def test_reblocks_only_when_evidence_changes_then_gives_up(tmp_path):
    state = tmp_path / "state"
    t = edit_no_check(tmp_path)
    assert run_hook(tmp_path, t, state_dir=state).returncode == 2
    # same evidence, harness re-entered: pass (no infinite loop)
    assert run_hook(tmp_path, t, stop_hook_active=True, state_dir=state).returncode == 0
    # the model then runs the check and it FAILS, and still claims: block again
    t2 = (Transcript(tmp_path, "t2").prompt("fix the parser")
          .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
          .tool("Bash", command="pytest -q", ok=False, output="1 failed")
          .text("All done — tests pass."))
    assert run_hook(tmp_path, t2.write(), stop_hook_active=True, state_dir=state).returncode == 2
    assert run_hook(tmp_path, t2.write(), stop_hook_active=True, state_dir=state).returncode == 0
    # third distinct failing state: block; fourth: budget exhausted
    t3 = (Transcript(tmp_path, "t3").prompt("fix the parser")
          .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
          .tool("Bash", command="pytest -q", ok=False, output="1 failed")
          .tool("Bash", command="pytest -q", ok=False, output="2 failed")
          .text("All done — tests pass."))
    assert run_hook(tmp_path, t3.write(), stop_hook_active=True, state_dir=state).returncode == 2
    t4 = (Transcript(tmp_path, "t4").prompt("fix the parser")
          .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
          .tool("Bash", command="pytest -q", ok=False, output="1 failed")
          .tool("Bash", command="pytest -q", ok=False, output="2 failed")
          .tool("Bash", command="pytest -q", ok=False, output="3 failed")
          .text("All done — tests pass."))
    assert run_hook(tmp_path, t4.write(), stop_hook_active=True, state_dir=state).returncode == 0


def test_only_the_current_turn_is_audited(tmp_path):
    # Turn 1 edited and passed its check (or not); turn 2 is a read-only question — the
    # answer must never be taxed for turn 1's edits.
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .text("Fixed — all tests pass.")
         .prompt("thanks, and what does parse_duration do?")
         .tool("Read", file_path="src/x.py")
         .text("It is done in two steps: parse the number, then the unit."))
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_meta_turns_do_not_start_a_new_turn(tmp_path):
    t = (Transcript(tmp_path).prompt("fix it")
         .tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
         .text("Done — all tests pass.")
         .prompt("Stop hook feedback:\nCLAIM AUDIT GATE ...", meta=True)
         .text("Done — all tests pass, really."))
    assert run_hook(tmp_path, t.write()).returncode == 2


# ---- delegation ----

def test_delegated_edits_are_audited(tmp_path):
    t = Transcript(tmp_path, "sess").prompt("fix it").tool("Agent", prompt="fix the parser", output="done")
    t.text("All done — the fix is implemented and verified.")
    main = t.write()
    sub = Transcript(tmp_path / "sess" / "subagents", "agent-a1")
    sub.n = 2  # inside the turn
    sub.tool("Edit", file_path="src/x.py", old_string="a", new_string="b").text("done").write()
    r = run_hook(tmp_path, main)
    assert r.returncode == 2 and "no test/check runner" in r.stderr


def test_delegated_edits_with_green_check_pass(tmp_path):
    t = Transcript(tmp_path, "sess").prompt("fix it").tool("Agent", prompt="fix the parser", output="done")
    t.text("All done — the fix is implemented and verified.")
    main = t.write()
    sub = Transcript(tmp_path / "sess" / "subagents" / "workflows" / "wf_1", "agent-a1")
    sub.n = 2
    sub.tool("Edit", file_path="src/x.py", old_string="a", new_string="b")
    sub.tool("Bash", command="pytest -q", output="12 passed").text("done").write()
    assert run_hook(tmp_path, main).returncode == 0


def test_delegation_without_readable_subagent_transcripts_is_conservative(tmp_path):
    t = Transcript(tmp_path, "sess").prompt("fix it").tool("Task", prompt="fix", output="done")
    t.text("All done — implemented and verified.")
    r = run_hook(tmp_path, t.write())
    assert r.returncode == 2 and "delegated" in r.stderr


def test_delegated_readonly_research_is_not_taxed(tmp_path):
    t = Transcript(tmp_path, "sess").prompt("audit").tool("Agent", prompt="read the code", output="findings")
    t.text("Audit complete — verified by reading.")
    main = t.write()
    sub = Transcript(tmp_path / "sess" / "subagents", "agent-a1")
    sub.n = 2
    sub.tool("Read", file_path="x.py").tool("Bash", command="grep -rn foo .", output="").text("findings").write()
    assert run_hook(tmp_path, main).returncode == 0


# ---- last message reconstruction ----

def test_last_message_is_reconstructed_from_the_final_message_id(tmp_path):
    # Claude Code writes one entry per content block; the gate must join the blocks of the
    # LAST assistant message, not take the last entry that happened to have text.
    t = Transcript(tmp_path).prompt("fix it").tool("Edit", file_path="x.py", old_string="a", new_string="b")
    t.text("Everything is implemented and all tests pass.", mid="msg_old")
    t.text("Actually, wait — ", mid="msg_final")
    t.text("the migration is not done yet; two parts remain to be fixed.", mid="msg_final")
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_transcript_fallback_when_no_payload_field(tmp_path):
    t = Transcript(tmp_path).prompt("fix it").tool("Edit", file_path="x.py", old_string="a", new_string="b")
    t.text("Everything is implemented and all tests pass.")
    assert run_hook(tmp_path, t.write()).returncode == 2


def test_payload_field_takes_precedence(tmp_path):
    t = Transcript(tmp_path).prompt("fix it").tool("Edit", file_path="x.py", old_string="a", new_string="b")
    t.text("still working on it")
    assert run_hook(tmp_path, t.write(), last_message="All done and verified.").returncode == 2


# ---- claim vocabulary ----

def test_german_completion_claims_block(tmp_path):
    for msg in ("Fertig. Alle Tests laufen grün.", "Der Bug ist behoben und alle Tests bestehen.",
                "Das Feature ist implementiert und abgeschlossen.", "Erledigt — die Umstellung ist umgesetzt.",
                "Alles funktioniert jetzt, der Bug ist gefixt.", "Ist korrigiert, läuft wieder durch.",
                "Die Tests laufen jetzt alle grün."):
        assert run_hook(tmp_path, edit_no_check(tmp_path, msg)).returncode == 2, msg


def test_german_in_progress_reports_do_not_block(tmp_path):
    for msg in ("Noch nicht fertig — zwei Teile fehlen.", "Der Bug ist noch nicht behoben.",
                "Nicht alle Tests laufen grün.", "Es funktioniert noch nicht.", "Läuft noch nicht durch."):
        assert run_hook(tmp_path, edit_no_check(tmp_path, msg)).returncode == 0, msg


def test_english_completion_phrasings_block(tmp_path):
    for msg in ("The fix is applied and the suite is green.", "It works now — the crash is gone.",
                "Ready to merge: CI is green, no failures.", "Everything checks out.", "All green.",
                "The bug is resolved.", "The crash was resolved by adding a null check.",
                "Tests are green now.", "All checks pass, done."):
        assert run_hook(tmp_path, edit_no_check(tmp_path, msg)).returncode == 2, msg


def test_honest_reports_do_not_block(tmp_path):
    for msg in ("The migration is not done yet; two parts remain to be fixed.",
                "Not all tests pass yet — two failures remain.", "No checks are green so far; still debugging.",
                "None of the tests pass on Windows yet.", "Two of the twelve tests pass so far.",
                "3 of 12 tests pass; the rest fail on encoding.", "Most tests pass but the parser suite fails.",
                "I was unable to complete the migration.", "Stopping here without having finished part 5.",
                "I could not fix the flaky test.", "I refactored the parser; next I plan to add tests."):
        assert run_hook(tmp_path, edit_no_check(tmp_path, msg)).returncode == 0, msg


def test_german_negation_does_not_swallow_a_following_claim(tmp_path):
    for msg in ("Der Fix ist nicht ganz trivial aber fertig.", "Das war nicht so schwer, alles fertig."):
        assert run_hook(tmp_path, edit_no_check(tmp_path, msg)).returncode == 2, msg
    assert run_hook(tmp_path, edit_no_check(tmp_path, "Der Fix ist nicht ganz fertig.")).returncode == 0


# ---- test edits ----

def test_test_file_edit_with_green_run_blocks_once_with_weakening_audit(tmp_path):
    state = tmp_path / "state"
    t = (Transcript(tmp_path).prompt("fix")
         .tool("Edit", file_path="tests/test_parser.py", old_string="assert x == 2", new_string="assert True")
         .tool("Bash", command="pytest -q", output="12 passed")
         .text("All tests pass now — done."))
    r = run_hook(tmp_path, t.write(), state_dir=state)
    assert r.returncode == 2 and "weakened" in r.stderr
    assert run_hook(tmp_path, t.write(), stop_hook_active=True, state_dir=state).returncode == 0


def test_windows_backslash_and_notebook_and_spec_paths_count_as_tests(tmp_path):
    for tool, inp in (("Edit", {"file_path": r"C:\repo\tests\test_parser.py"}),
                      ("NotebookEdit", {"notebook_path": "tests/test_nb.ipynb"}),
                      ("Write", {"file_path": "src/auth.spec.ts"})):
        t = Transcript(tmp_path).prompt("fix").tool(tool, **inp).tool("Bash", command="pytest -q", output="ok")
        r = run_hook(tmp_path, t.text("All tests pass now — done.").write())
        assert r.returncode == 2 and "weakened" in r.stderr, tool


def test_bash_write_to_test_file_adds_weakening_audit(tmp_path):
    t = (Transcript(tmp_path).prompt("fix")
         .tool("Bash", command="sed -i 's/assert x == 2/assert True/' tests/test_math.py", output="")
         .tool("Bash", command="pytest -q", output="ok").text("All tests pass now — done."))
    r = run_hook(tmp_path, t.write())
    assert r.returncode == 2 and "weakened" in r.stderr
    t = (Transcript(tmp_path).prompt("fix")
         .tool("Edit", file_path="src/parser.py", old_string="a", new_string="b")
         .tool("Bash", command="pytest tests/test_x.py -q > out.log", output="").text("All tests pass — done."))
    assert run_hook(tmp_path, t.write()).returncode == 0


def test_non_test_edit_has_no_weakening_audit(tmp_path):
    r = run_hook(tmp_path, edit_no_check(tmp_path, "All tests pass now — done."))
    assert r.returncode == 2 and "weakened" not in r.stderr


# ---- fail-open ----

def test_malformed_stdin_fails_open(tmp_path):
    assert run_hook(tmp_path, tmp_path / "x.jsonl", raw_stdin="this is not json").returncode == 0


def test_missing_transcript_fails_open(tmp_path):
    assert run_hook(tmp_path, tmp_path / "nope.jsonl", last_message="Done and verified.").returncode == 0


def test_garbage_transcript_lines_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    t = Transcript(tmp_path).prompt("fix").tool("Edit", file_path="x", old_string="a", new_string="b")
    p.write_text("not json\n[1,2,3]\n" + "\n".join(json.dumps(e) for e in t.entries))
    assert run_hook(tmp_path, p, last_message="Done, verified.").returncode == 2


def test_non_ascii_transcript_does_not_disable_the_gate(tmp_path):
    t = Transcript(tmp_path).prompt("fix").text("Working on the parser \U0001f355 with umlauts: äöü")
    t.tool("Edit", file_path="x.py", old_string="a", new_string="b")
    p = t.write()
    payload = {"transcript_path": str(p), "stop_hook_active": False, "session_id": "s",
               "last_assistant_message": "Fertig \U0001f389 — all tests pass."}
    env = dict(os.environ, PYTHONIOENCODING="cp1252", HARDMODE_STATE_DIR=str(tmp_path / "state"))
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=30, env=env)
    assert r.returncode == 2


def test_decisions_are_written_to_the_ledger(tmp_path):
    state = tmp_path / "state"
    run_hook(tmp_path, edit_no_check(tmp_path), state_dir=state)
    recs = [json.loads(ln) for ln in (state / "ledger-s1.jsonl").read_text().splitlines()]
    assert recs[-1]["hook"] == "claim-audit" and recs[-1]["outcome"] == "block" and recs[-1]["detail"] == "no-check"
