#!/usr/bin/env python3
"""Live demo of the hardmode deterministic hooks (stdlib-only, cross-platform).

Runs the ACTUAL shipped hooks (../claude/hooks/*.py, resolved relative to this
script) as subprocesses against synthetic payloads, in a throwaway sandbox
(tempfile HARDMODE_STATE_DIR + a scratch `git init` repo for the guard's dirty-tree
checks). Never touches ~/.claude or any real state: every hook run has its
HARDMODE_STATE_DIR pinned to the sandbox.

Each scenario asserts the hook's exit code internally, so the demo is itself a
test. It prints `demo: N/N scenarios behaved as expected` and exits 0, or reports
the deviation and exits 1. Output is deterministic (no timestamps/randomness) and
plain ASCII except the intentional emoji in the compaction scenario.

Usage:  python tools/demo.py   |   python tools/demo.py --list
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows consoles default to cp1252; the emoji + umlauts in scenario (e) need a
# utf-8 stdout. Mirror the hooks' own reconfigure-or-ignore pattern.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOOKS = Path(__file__).resolve().parent.parent / "claude" / "hooks"
STATE_DIR = ""  # a fresh tempdir, assigned in main(); no real state is ever touched


class Deviation(Exception):
    """A hook returned an exit code the scenario did not expect."""


def run_hook(hook, payload):
    """Run a shipped hook as a subprocess: payload -> utf-8 JSON on stdin. Returns
    (exit_code, stdout, stderr) as text. HARDMODE_STATE_DIR is pinned to the sandbox
    and HARDMODE_LOOP_THRESHOLD is cleared so the run is deterministic regardless of
    the caller's environment."""
    env = dict(os.environ)
    env.pop("HARDMODE_LOOP_THRESHOLD", None)
    env["HARDMODE_STATE_DIR"] = STATE_DIR
    p = subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=30, env=env,
    )
    return (p.returncode, p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


def snippet(text, n=78):
    """One-line, whitespace-collapsed excerpt of a hook's stderr for narration."""
    t = " ".join(text.split())
    return (t[:n] + " ...") if len(t) > n else t


def expect(code, want, what):
    if code != want:
        raise Deviation(f"{what}: expected exit {want}, got {code}")


def write_transcript(name, entries):
    p = Path(STATE_DIR) / name
    p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries),
                 encoding="utf-8")
    return str(p)


def make_scratch_repo():
    """A git repo with one uncommitted (untracked) file, so `git status --porcelain`
    reports a dirty tree the guard must protect."""
    repo = Path(STATE_DIR) / "scratch-repo"
    if not repo.exists():
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        (repo / "work.txt").write_text("uncommitted work", encoding="utf-8")
    return str(repo)


# --- scenarios ---------------------------------------------------------------

def sc_claim_audit(n):
    print(f"\nSCENARIO {n}  the model claims victory without running the tests")
    tp = write_transcript("claim.jsonl", [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "src/parser.py"}}]}},
    ])
    base = {"transcript_path": tp, "stop_hook_active": False}
    code, _, err = run_hook("stop-claim-audit.py",
                            dict(base, last_assistant_message="All done - tests pass."))
    print('  model:  edited src/parser.py, final message: "All done - tests pass."')
    print(f'  kit:    BLOCKED (claim-audit gate) -> "{snippet(err)}"')
    expect(code, 2, "claim-audit false claim")
    code, _, _ = run_hook("stop-claim-audit.py",
                          dict(base, last_assistant_message="Not all tests pass yet - two failures remain."))
    print('  model:  honest instead: "Not all tests pass yet - two failures remain."')
    print("  kit:    ALLOWED (exit 0) -- not a nag machine; honest reports end the session")
    expect(code, 0, "claim-audit honest report")
    print("  [ok]")


def sc_destructive(n):
    print(f"\nSCENARIO {n}  reflexive destructive commands on a dirty tree")
    repo = make_scratch_repo()

    def guard(cmd):
        return run_hook("pretool-destructive-guard.py",
                        {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": repo})

    code, _, err = guard("git reset --hard")
    print("  bash:   git reset --hard           (scratch repo has 1 uncommitted file)")
    print(f'  kit:    BLOCKED (destructive guard) -> "{snippet(err)}"')
    expect(code, 2, "guard git reset --hard on dirty tree")

    code, _, err = guard("rm -rf build/ /")
    print("  bash:   rm -rf build/ /            (the classic stray-space typo)")
    print(f'  kit:    BLOCKED (destructive guard) -> "{snippet(err)}"')
    expect(code, 2, "guard stray-space rm")

    code, _, _ = guard("rm -rf build/")
    print("  bash:   rm -rf build/             (scoped and recoverable)")
    print("  kit:    ALLOWED (exit 0) -- scoped deletes pass untouched")
    expect(code, 0, "guard scoped rm")

    code, _, _ = guard("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard")
    print("  bash:   HARDMODE_DESTRUCTIVE_OK=1 git reset --hard   (user-approved escape hatch)")
    print("  kit:    ALLOWED (exit 0) -- override honored for this one command only")
    expect(code, 0, "guard override")
    print("  [ok]")


def sc_loop_alarm(n):
    print(f"\nSCENARIO {n}  the same failing command, run and re-run")
    payload = {"session_id": "demo-loop", "hook_event_name": "PostToolUseFailure",
               "tool_name": "Bash", "tool_input": {"command": "python -m pytest -q"},
               "tool_response": {}}
    print('  bash:   "python -m pytest -q" fails 3x, nothing changed in between')
    for attempt in (1, 2, 3):
        code, _, err = run_hook("posttool-loop-alarm.py", payload)
        if attempt < 3:
            print(f"  kit:    attempt {attempt} -> silent (exit 0), iteration is legitimate")
            expect(code, 0, f"loop alarm attempt {attempt}")
        else:
            print(f'  kit:    attempt {attempt} -> LOOP ALARM nudge (exit 2) -> "{snippet(err)}"')
            expect(code, 2, "loop alarm third failure")
    print("  [ok]")


def sc_compaction(n):
    print(f"\nSCENARIO {n}  context compaction must not lose the original request")
    request = "Baue das Zahlungs-Widget \U0001f355 mit Umlauten: äöüß"
    tp = write_transcript("compact.jsonl", [{"type": "user", "message": {"content": request}}])
    code, _, _ = run_hook("precompact-save-task.py",
                          {"session_id": "demo-compact", "transcript_path": tp})
    print("  precompact: saves the first user message verbatim (emoji + umlauts survive)")
    expect(code, 0, "precompact save")
    code, out, _ = run_hook("sessionstart-compact-recovery.py",
                            {"session_id": "demo-compact", "cwd": STATE_DIR})
    expect(code, 0, "compact recovery exit")
    if request not in out:
        raise Deviation("compact recovery: original request not echoed back")
    print(f'  request:    "{request}"')
    print(f'  kit:    RECOVERED verbatim after compaction -> "{request}"')
    print("  [ok]")


SCENARIOS = [
    ("claim-audit: false completion claim is blocked; honest report passes", sc_claim_audit),
    ("destructive-guard: reflexive git reset / rm on a dirty tree", sc_destructive),
    ("loop-alarm: the same failing command three times", sc_loop_alarm),
    ("compaction-recovery: original request survives a compaction", sc_compaction),
]


def main(argv):
    if "--list" in argv:
        for i, (name, _) in enumerate(SCENARIOS, 1):
            print(f"{i}  {name}")
        return 0
    global STATE_DIR
    STATE_DIR = tempfile.mkdtemp(prefix="hardmode-demo-")
    print("hardmode hooks -- live demo (the real shipped hooks catch these failure modes)")
    passed = 0
    try:
        for i, (_, fn) in enumerate(SCENARIOS, 1):
            try:
                fn(i)
                passed += 1
            except Deviation as e:
                print(f"  [FAIL] {e}")
            except Exception as e:  # a hook crash or setup failure is a scenario failure
                print(f"  [FAIL] scenario {i} errored: {e!r}")
    finally:
        shutil.rmtree(STATE_DIR, ignore_errors=True)
    total = len(SCENARIOS)
    print(f"\ndemo: {passed}/{total} scenarios behaved as expected")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
