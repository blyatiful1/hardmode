#!/usr/bin/env python3
"""SessionStart floor check (hardmode) — startup | resume | clear (never compact).

Two jobs, both about the failure mode the kit fears most: the deterministic floor
going silently inert after a harness change.

1. WITNESS ITSELF. It writes one `floor-check:ran` record to the session ledger.
   A session summary without that record is a session in which plugin hooks did not
   run at all (disableAllHooks, allowManagedHooksOnly, workspace trust not accepted,
   plugin disabled) — which tools/stats.py then reports as such, instead of the
   silence reading as "nothing needed to fire".

2. SELF-TEST ON HARNESS CHANGE. It fingerprints the `claude` binary (size + mtime of
   the resolved path). When the fingerprint differs from the last one seen, it runs
   the kit's own demo (tools/demo.py — the real hooks against planted failure modes)
   and injects ONE line into the session context: the scenario count on success, or
   the failing scenarios under "HARDMODE FLOOR DEGRADED" — at the one moment the
   driver can act on it. Unchanged harness: one stat() call, no output.

It also relays what fired in the PREVIOUS session (one line, only when something
did), so a block or nudge is never invisible history.

Output is capped, stdout is context (SessionStart), exit is always 0. Set
HARDMODE_SELFTEST=0 to disable the demo run.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import iter_jsonl, ledger, reconfigure_utf8, session_slug, state_dir  # noqa: E402

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_TIMEOUT = 40
MAX_OUT = 700


def harness_fingerprint():
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        st = os.stat(os.path.realpath(exe))
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return None


def self_test():
    """(ok, summary) from the real demo; None if it could not run at all."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or PLUGIN_ROOT
    demo = os.path.join(root, "tools", "demo.py")
    if not os.path.isfile(demo):
        return None
    env = dict(os.environ)
    for k in ("HARDMODE_STATE_DIR", "HARDMODE_LEDGER", "HARDMODE_LOOP_THRESHOLD", "HARDMODE_DESTRUCTIVE_OK",
              "HARDMODE_PREFLIGHT", "HARDMODE_READONLY_AGENTS", "HARDMODE_MEM_FS_CASE_INSENSITIVE",
              "HARDMODE_SELFTEST", "CLAUDE_DIR", "CLAUDE_CODE_REMOTE_MEMORY_DIR"):
        env.pop(k, None)
    try:
        p = subprocess.run([sys.executable, demo, "--quiet"], capture_output=True, text=True,
                           timeout=DEMO_TIMEOUT, env=env)
    except Exception:
        return None
    tail = [ln for ln in (p.stdout + p.stderr).splitlines() if ln.strip()]
    summary = next((ln for ln in reversed(tail) if ln.startswith("demo:")), tail[-1] if tail else "")
    fails = [ln for ln in tail if "[FAIL]" in ln][:4]
    return p.returncode == 0, summary, fails


def previous_session_line(d, this_session):
    last = None
    for rec in iter_jsonl(os.path.join(d, "sessions.jsonl")):
        if rec.get("session") != this_session:
            last = rec
    if not last:
        return ""
    fired = {k: v for k, v in (last.get("by_hook") or {}).items()
             if k.split(":")[-1] in ("block", "nudge", "deny", "deny-edit", "override")}
    if not fired:
        return ""
    parts = ", ".join(f"{k.replace(':', ' ')} x{v}" for k, v in sorted(fired.items()))
    return f"hardmode: in the previous session the floor fired — {parts}."


def main():
    reconfigure_utf8(sys.stdin, sys.stdout)
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if data.get("source") == "compact":
        return 0                      # the recovery hook owns that path
    d = state_dir()
    ledger(data, "floor-check", "ran", data.get("source") or "")
    degraded, info = "", ""
    fp = harness_fingerprint()
    if fp and os.environ.get("HARDMODE_SELFTEST", "1") != "0":
        fp_path = os.path.join(d, "harness-fp.txt")
        try:
            with open(fp_path, encoding="utf-8") as f:
                seen = f.read().strip()
        except OSError:
            seen = ""
        if seen != fp:
            why = "first session on this machine" if not seen else "Claude Code binary changed since the last check"
            res = self_test()
            if res is None:
                info = (f"hardmode: {why}; the hook self-test could not run (python3/tools/demo.py "
                        "unavailable) — run `python3 tools/demo.py` yourself.")
                ledger(data, "floor-check", "selftest-unavailable")
            elif res[0]:
                # remember this binary ONLY on a green self-test, so a degraded floor is
                # re-tested and re-announced every session until it is fixed
                try:
                    with open(fp_path, "w", encoding="utf-8") as f:
                        f.write(fp)
                except OSError:
                    pass
                info = f"hardmode: {why}; hook self-test OK ({res[1]})."
                ledger(data, "floor-check", "selftest-ok", res[1])
            else:
                degraded = (f"HARDMODE FLOOR DEGRADED — {why} and the hook self-test FAILED ({res[1]}). "
                            "These guards are no longer firing: " + " | ".join(res[2])
                            + " — treat their advisory rules as unenforced until fixed.")
                ledger(data, "floor-check", "selftest-fail", res[1])
    prev = previous_session_line(d, session_slug(data))
    parts = [p for p in (degraded[:MAX_OUT], info[:300], prev[:300]) if p]
    if parts:
        print("\n".join(parts))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
