# Tests for tools/demo.py -- runs the demo as a subprocess (like the neighbouring
# hook tests) and checks it behaves as its own self-test and leaves no state behind.
import os
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo.py"


def run_demo(env=None, args=()):
    # The demo emits utf-8 (the compaction scenario prints an emoji); decode as utf-8
    # rather than the Windows console default (cp1252), which cannot decode it.
    return subprocess.run([sys.executable, str(DEMO), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=120, env=env)


def test_demo_runs_green_and_narrates_a_block():
    r = run_demo()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BLOCKED (claim-audit gate)" in r.stdout
    assert "scenarios behaved as expected" in r.stdout
    assert "4/4 scenarios behaved as expected" in r.stdout


def test_list_prints_names_without_running_scenarios():
    r = run_demo(args=["--list"])
    assert r.returncode == 0
    assert "claim-audit" in r.stdout
    assert "[ok]" not in r.stdout  # --list must not execute any scenario


def test_demo_writes_no_state_to_the_users_real_dir(tmp_path):
    # The demo pins every hook's HARDMODE_STATE_DIR to its own throwaway sandbox, so a
    # run must add nothing to the user's real hardmode state dir (the fallback
    # location ~/.claude/tmp/hardmode). Point all temp roots at an isolated box
    # (so the sandbox itself lands under tmp_path) and confirm the real dir is
    # untouched -- a direct check of the "never touches real state" promise.
    real_state = Path.home() / ".claude" / "tmp" / "hardmode"

    def snapshot():
        return {p.name for p in real_state.iterdir()} if real_state.exists() else None

    before = snapshot()
    box = tmp_path / "box"
    box.mkdir()
    env = dict(os.environ, TMPDIR=str(box), TEMP=str(box), TMP=str(box))
    env.pop("HARDMODE_STATE_DIR", None)  # leave the fallback path as the only thing that could leak
    r = run_demo(env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert snapshot() == before  # nothing added to (or removed from) the real state dir
