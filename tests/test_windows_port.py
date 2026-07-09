# Windows-port guards. The kit's Windows surface is a PARALLEL implementation
# (install.ps1 / doctor.ps1 / *-windows*.json snippets) of behavior the POSIX
# scripts already test — parallel implementations drift silently, so every test
# here either pins the Windows artifact to its POSIX twin or exercises the
# PowerShell scripts end-to-end the same way test_install_doctor.py does bash.
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "claude" / "settings"
INSTALL_PS = ROOT / "install.ps1"
DOCTOR_PS = ROOT / "tools" / "doctor.ps1"
PWSH = shutil.which("pwsh")

# unix snippet -> windows snippet: same kit, different python launcher spelling.
PAIRS = [
    ("settings-snippet.json", "settings-snippet-windows.json"),
    ("settings-snippet-small.json", "settings-snippet-windows-small.json"),
]


def load(name):
    return json.loads((SETTINGS / name).read_text())


def without_comment(snippet):
    return {k: v for k, v in snippet.items() if k != "//"}


# ---- snippet consistency (runs everywhere) ----

def test_windows_snippets_mirror_unix():
    # The Windows snippets must be the Unix snippets with `python3 ` -> `python `
    # in hook commands and nothing else different (comment aside). Any drift means
    # Windows installs silently diverge from the tested configuration.
    for unix_name, win_name in PAIRS:
        unix = without_comment(load(unix_name))
        win = without_comment(load(win_name))
        normalized = json.loads(
            json.dumps(unix).replace("python3 ~/.claude/hooks/", "python ~/.claude/hooks/"))
        assert normalized == win, f"{win_name} drifted from {unix_name}"


def test_windows_snippets_never_invoke_python3():
    # Windows Pythons ship no `python3` launcher — a python3 command in the
    # Windows snippet is a hook that never fires.
    for _, win_name in PAIRS:
        for groups in load(win_name)["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    assert "python3" not in hook["command"], \
                        f"{win_name}: {hook['command']}"


def test_windows_small_variant_sets_loop_threshold():
    small = load("settings-snippet-windows-small.json")
    assert small["env"]["FABLE_LOOP_THRESHOLD"] == "2"
    assert "FABLE_LOOP_THRESHOLD" not in load("settings-snippet-windows.json").get("env", {})


# ---- install.ps1 / doctor.ps1 end-to-end (needs pwsh; CI has it on both OSes) ----

requires_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh not on PATH")
requires_bash_too = pytest.mark.skipif(
    PWSH is None or os.name == "nt", reason="needs pwsh AND the POSIX installer")


def run_ps(script, claude_dir, *args, state_dir=None):
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir))
    if state_dir:
        env["FABLE_STATE_DIR"] = str(state_dir)
    return subprocess.run([PWSH, "-NoProfile", "-File", str(script), *args],
                          capture_output=True, text=True, timeout=180, env=env)


def run_sh(script, claude_dir):
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, CLAUDE_DIR=str(claude_dir)))


def install_and_merge_settings(claude_dir):
    r = run_ps(INSTALL_PS, claude_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    snippet = load("settings-snippet-windows.json")
    (claude_dir / "settings.json").write_text(json.dumps(snippet))


@requires_pwsh
def test_install_ps1_installs_everything_idempotently(tmp_path):
    claude = tmp_path / "claude"
    r = run_ps(INSTALL_PS, claude)
    assert r.returncode == 0, r.stdout + r.stderr
    for rel in ("hooks/stop-claim-audit.py", "agents/verifier.md",
                "workflows/paranoid-review.js", "skills/fable/SKILL.md",
                "skills/webdesign/references/german-market.md",
                "cli/mem.py", "memory/privacy.toml", "CLAUDE.md"):
        assert (claude / rel).is_file(), f"{rel} did not install"
    # Second run: nothing changed, nothing backed up (same invariant as install.sh).
    r2 = run_ps(INSTALL_PS, claude)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "webdesign (unchanged)" in r2.stdout
    assert not (claude / "fable-protocol-backups").exists(), \
        "idempotent re-run must not churn backups"
    # Backups must never create loadable duplicates inside skills/.
    shipped = {p.name for p in (ROOT / "claude" / "skills").iterdir() if p.is_dir()}
    installed = {p.name for p in (claude / "skills").iterdir()}
    assert installed == shipped


@requires_pwsh
def test_install_ps1_preserves_user_extra_files_in_skill_dir(tmp_path):
    claude = tmp_path / "claude"
    assert run_ps(INSTALL_PS, claude).returncode == 0
    extra = claude / "skills" / "webdesign" / "references" / "my-notes.md"
    extra.write_text("mine\n")
    r2 = run_ps(INSTALL_PS, claude)
    assert r2.returncode == 0
    assert "webdesign (unchanged)" in r2.stdout
    assert extra.read_text() == "mine\n"


@requires_pwsh
def test_install_ps1_prunes_formerly_shipped_skill_files(tmp_path):
    claude = tmp_path / "claude"
    assert run_ps(INSTALL_PS, claude).returncode == 0
    sk = claude / "skills" / "webdesign"
    stale = sk / "references" / "old-checklist.md"
    stale.write_text("outdated legal advice\n")
    manifest = sk / ".fable-manifest"
    manifest.write_text(manifest.read_text() + "./references/old-checklist.md\n")
    mine = sk / "references" / "my-notes.md"
    mine.write_text("mine\n")
    r2 = run_ps(INSTALL_PS, claude)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert not stale.exists(), "manifest-tracked stale file must be pruned on upgrade"
    assert mine.read_text() == "mine\n", "user file must survive the upgrade"
    assert "old-checklist" not in manifest.read_text()


@requires_pwsh
def test_install_ps1_tier_small_prints_small_snippet(tmp_path):
    claude = tmp_path / "claude"
    r = run_ps(INSTALL_PS, claude, "-Tier", "small")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FABLE_LOOP_THRESHOLD" in r.stdout, "-Tier small must print the small snippet"
    assert "big-task" in r.stdout, "small-tier guidance should point at /big-task"


@requires_pwsh
def test_install_ps1_unknown_flag_fails_loudly(tmp_path):
    r = run_ps(INSTALL_PS, tmp_path / "claude", "-Bogus")
    assert r.returncode != 0


@requires_pwsh
def test_install_ps1_default_does_not_pin_models(tmp_path):
    claude = tmp_path / "claude"
    assert run_ps(INSTALL_PS, claude).returncode == 0
    for agent in (claude / "agents").glob("*.md"):
        assert "\nmodel:" not in agent.read_text(), f"{agent.name} unexpectedly pinned"


@requires_pwsh
def test_install_ps1_strong_model_pins_verification_agents(tmp_path):
    claude = tmp_path / "claude"
    r = run_ps(INSTALL_PS, claude, "-StrongModel", "opus")
    assert r.returncode == 0, r.stdout + r.stderr
    for agent in ("verifier", "oracle", "plan-critic"):
        text = (claude / "agents" / f"{agent}.md").read_text()
        frontmatter = text.split("---")[1]
        assert "model: opus" in frontmatter, f"{agent} not pinned"


@requires_pwsh
def test_doctor_ps1_passes_on_full_install(tmp_path):
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    r = run_ps(DOCTOR_PS, claude, state_dir=tmp_path / "state")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DOCTOR: installation verified" in r.stdout
    assert "FAIL" not in r.stdout


@requires_pwsh
def test_doctor_ps1_fails_without_settings_merge(tmp_path):
    # The exact real-world failure the doctor exists for: install ran, the
    # manual settings merge did not — every hook silently unwired.
    claude = tmp_path / "claude"
    assert run_ps(INSTALL_PS, claude).returncode == 0
    r = run_ps(DOCTOR_PS, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "settings.json missing" in r.stdout


@requires_pwsh
def test_doctor_ps1_fails_on_unwired_hook(tmp_path):
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    settings = json.loads((claude / "settings.json").read_text())
    del settings["hooks"]["Stop"]  # un-wire the benchmarked gate
    (claude / "settings.json").write_text(json.dumps(settings))
    r = run_ps(DOCTOR_PS, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "stop-claim-audit.py" in r.stdout and "NOT wired" in r.stdout


@requires_pwsh
def test_doctor_ps1_warns_on_python3_settings(tmp_path):
    # A Windows user who merged the UNIX snippet has hooks that never fire —
    # the doctor must at least say so.
    claude = tmp_path / "claude"
    assert run_ps(INSTALL_PS, claude).returncode == 0
    (claude / "settings.json").write_text(json.dumps(load("settings-snippet.json")))
    r = run_ps(DOCTOR_PS, claude, state_dir=tmp_path / "state")
    assert "invokes 'python3'" in r.stdout


# ---- cross-tool parity: a machine that uses both installers must not churn ----

@requires_bash_too
def test_ps1_install_is_byte_compatible_with_bash_install(tmp_path):
    sh_dir, ps_dir = tmp_path / "sh", tmp_path / "ps"
    assert run_sh(ROOT / "install.sh", sh_dir).returncode == 0
    assert run_ps(INSTALL_PS, ps_dir).returncode == 0
    # Same skill manifests byte-for-byte (format AND ordering).
    for d in (ROOT / "claude" / "skills").iterdir():
        a = (sh_dir / "skills" / d.name / ".fable-manifest").read_bytes()
        b = (ps_dir / "skills" / d.name / ".fable-manifest").read_bytes()
        assert a == b, f"manifest for {d.name} differs between installers"
    # install.ps1 over a bash install: everything reads as unchanged.
    r = run_ps(INSTALL_PS, sh_dir)
    assert r.returncode == 0
    assert "backed up" not in r.stdout, "ps1 over a bash install must not churn backups"


@requires_bash_too
def test_ps1_strong_model_output_matches_bash(tmp_path):
    sh_dir, ps_dir = tmp_path / "sh", tmp_path / "ps"
    r = subprocess.run(["bash", str(ROOT / "install.sh"), "--strong-model", "opus"],
                       capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, CLAUDE_DIR=str(sh_dir)))
    assert r.returncode == 0
    assert run_ps(INSTALL_PS, ps_dir, "-StrongModel", "opus").returncode == 0
    for agent in ("verifier", "oracle", "plan-critic"):
        a = (sh_dir / "agents" / f"{agent}.md").read_bytes()
        b = (ps_dir / "agents" / f"{agent}.md").read_bytes()
        assert a == b, f"pinned {agent}.md differs between installers"
