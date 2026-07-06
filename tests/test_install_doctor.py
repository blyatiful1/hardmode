# End-to-end: install.sh followed by tools/doctor.sh against a scratch CLAUDE_DIR.
# This is the closest thing to "does the protocol actually arrive on a machine"
# that runs without a live Claude Code session.
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
DOCTOR = ROOT / "tools" / "doctor.sh"


def run(script, claude_dir, state_dir=None):
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir))
    if state_dir:
        env["FABLE_STATE_DIR"] = str(state_dir)
    return subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          timeout=60, env=env)


def install_and_merge_settings(claude_dir):
    r = run(INSTALL, claude_dir)
    assert r.returncode == 0, r.stderr
    snippet = json.loads((ROOT / "claude" / "settings" / "settings-snippet.json").read_text())
    (claude_dir / "settings.json").write_text(json.dumps(snippet))


def test_doctor_passes_on_full_install(tmp_path):
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DOCTOR: installation verified" in r.stdout
    assert "FAIL" not in r.stdout


def test_doctor_fails_without_settings_merge(tmp_path):
    # The exact real-world failure the doctor exists for: install ran, the
    # manual settings merge did not — every hook silently unwired.
    claude = tmp_path / "claude"
    r = run(INSTALL, claude)
    assert r.returncode == 0
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "settings.json missing" in r.stdout


def test_doctor_fails_on_unwired_hook(tmp_path):
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    settings = json.loads((claude / "settings.json").read_text())
    del settings["hooks"]["Stop"]  # un-wire the benchmarked gate
    (claude / "settings.json").write_text(json.dumps(settings))
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "stop-claim-audit.py" in r.stdout and "NOT wired" in r.stdout


def test_doctor_fails_on_missing_hook_file(tmp_path):
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    (claude / "hooks" / "stop-claim-audit.py").unlink()
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "hook missing" in r.stdout


def test_doctor_fails_on_invalid_settings_json(tmp_path):
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    (claude / "settings.json").write_text("{ not json")
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "not valid JSON" in r.stdout


def test_doctor_flags_unmerged_doctrine(tmp_path):
    claude = tmp_path / "claude"
    claude.mkdir(parents=True)
    (claude / "CLAUDE.md").write_text("# my own doctrine\n")  # pre-existing, no kit section
    install_and_merge_settings(claude)
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "CLAUDE.fable-protocol.md" in r.stdout
