"""Small-driver tier: snippet sync, installer flags, model pinning. Self-contained."""
import json
import os
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
BASE = json.loads((REPO / "claude/settings/settings-snippet.json").read_text())
SMALL = json.loads((REPO / "claude/settings/settings-snippet-small.json").read_text())

# The POSIX installer path: on Windows, bare `bash` is the WSL stub (which even
# fails with a nonzero exit — a false green for the unknown-flag test). Windows
# exercises the same flags against install.ps1 in test_windows_port.py.
requires_bash = pytest.mark.skipif(os.name == "nt", reason="POSIX installer path")


def test_small_snippet_is_base_plus_loop_threshold():
    """The small snippet must never drift from the base except the documented delta."""
    assert SMALL["hooks"] == BASE["hooks"], "hook wiring must be identical across tiers"
    assert SMALL["effortLevel"] == BASE["effortLevel"]
    small_env = dict(SMALL["env"])
    assert small_env.pop("FABLE_LOOP_THRESHOLD") == "2"
    assert small_env == BASE["env"], "small env must be base env + FABLE_LOOP_THRESHOLD only"


def run_install(tmp_path, *flags):
    dst = tmp_path / "claude-home"
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), *flags],
        env={"CLAUDE_DIR": str(dst), "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return dst, r.stdout


@requires_bash
def test_default_install_does_not_pin_models(tmp_path):
    dst, _ = run_install(tmp_path)
    for agent in (dst / "agents").glob("*.md"):
        assert "\nmodel:" not in agent.read_text(), f"{agent.name} unexpectedly pinned"


@requires_bash
def test_strong_model_flag_pins_all_agent_frontmatter(tmp_path):
    dst, _ = run_install(tmp_path, "--strong-model", "opus")
    agents = list((dst / "agents").glob("*.md"))
    assert agents, "no agents installed"
    for agent in agents:
        text = agent.read_text()
        fm = text.split("---")[1]  # frontmatter block
        assert "\nmodel: opus\n" in fm, f"{agent.name} frontmatter not pinned: {fm!r}"


@requires_bash
def test_pinned_install_is_idempotent(tmp_path):
    dst, _ = run_install(tmp_path, "--strong-model", "opus")
    before = {p.name: p.read_text() for p in (dst / "agents").glob("*.md")}
    _, out2 = run_install(tmp_path, "--strong-model", "opus")
    after = {p.name: p.read_text() for p in (dst / "agents").glob("*.md")}
    assert before == after
    for name in before:
        assert f"{name} (unchanged)" in out2, f"re-run re-copied {name} — pin not durable"
    backups = dst / "fable-protocol-backups"
    assert not backups.exists() or not any(backups.iterdir()), "idempotent re-run made backups"


@requires_bash
def test_tier_small_prints_small_snippet(tmp_path):
    _, out = run_install(tmp_path, "--tier", "small")
    assert "FABLE_LOOP_THRESHOLD" in out, "--tier small must print the small snippet"
    assert "big-task" in out, "small-tier guidance should point at /big-task"


@requires_bash
def test_unknown_flag_fails_loudly(tmp_path):
    r = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--bogus"],
        env={"CLAUDE_DIR": str(tmp_path / "x"), "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True,
    )
    assert r.returncode != 0


def test_big_task_workflow_shipped_and_referenced():
    assert (REPO / "claude/workflows/big-task.js").exists()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "/big-task" in readme
    assert "ultracode" in readme, "README must document the ultracode composition story"
    skill = (REPO / "claude/skills/orchestrate/SKILL.md").read_text()
    assert "ultracode" in skill, "orchestrate skill must teach the opt-in rule"
    assert "budget.total" in skill, "orchestrate skill must teach budget guards"
