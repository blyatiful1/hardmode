# Tests for tools/demo.py — the demo is itself a self-test of every shipped hook and of the wiring.
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tools" / "demo.py"


def run_demo(env=None, args=()):
    return subprocess.run([sys.executable, str(DEMO), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=180, env=env)


def test_demo_runs_green_and_narrates_a_block():
    r = run_demo()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BLOCKED (claim-audit gate)" in r.stdout
    assert "10/10 scenarios behaved as expected" in r.stdout


def test_quiet_prints_only_the_summary():
    r = run_demo(args=["--quiet"])
    assert r.returncode == 0
    assert r.stdout.strip() == "demo: 10/10 scenarios behaved as expected"


def test_list_prints_names_without_running_scenarios():
    r = run_demo(args=["--list"])
    assert r.returncode == 0
    assert "claim-audit" in r.stdout and "wiring" in r.stdout
    assert "[ok]" not in r.stdout


def test_every_shipped_hook_has_a_scenario():
    # A hook without a demo scenario is a hook whose inertness after a harness change
    # nobody would notice.
    src = DEMO.read_text(encoding="utf-8")
    for hook in sorted((ROOT / "hooks").glob("*.py")):
        if hook.name.startswith("_"):
            continue
        assert hook.name in src, f"{hook.name} has no demo scenario"


def test_demo_writes_no_state_to_the_users_real_dir(tmp_path):
    claude_dir = Path.home() / ".claude"
    watched = [claude_dir / "tmp" / "hardmode", claude_dir / "memory", claude_dir / "projects"]

    def snapshot():
        out = {}
        for d in watched:
            out[str(d)] = sorted((str(p.relative_to(d)), p.stat().st_mtime_ns) for p in d.rglob("*")) if d.exists() else None
        return out

    before = snapshot()
    box = tmp_path / "box"
    box.mkdir()
    env = dict(os.environ, TMPDIR=str(box), TEMP=str(box), TMP=str(box))
    env.pop("HARDMODE_STATE_DIR", None)
    r = run_demo(env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert snapshot() == before, "the demo touched the operator's real ~/.claude state, memory or projects"


def test_readme_console_block_matches_the_real_demo_output():
    # The README shows the demo's output as a console transcript; every SCENARIO line
    # it prints must be a real line the program emits.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```console\n\$ python tools/demo.py\n(.*?)```", readme, re.S)
    assert block, "README has no demo console block"
    real = run_demo().stdout.splitlines()
    shown = [ln for ln in block.group(1).splitlines() if ln.strip()]
    assert shown, "README demo block is empty"
    # ...every line, in the order the program prints them (repeated lines such as `[ok]`
    # are matched as a subsequence, not by first occurrence)
    pos = 0
    for line in shown:
        try:
            pos = real.index(line, pos) + 1
        except ValueError:
            raise AssertionError(f"README demo transcript line is not real output (in order): {line!r}") from None
