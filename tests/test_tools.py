# Tests for tools/doctor.py, tools/stats.py, tools/memcheck.py and the commands/ that run them.
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def run(tool, args, cfg, env_extra=None):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg), HARDMODE_STATE_DIR=str(cfg / "tmp" / "hardmode"))
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env.pop("CLAUDE_CODE_REMOTE_MEMORY_DIR", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(TOOLS / tool), *args], capture_output=True, text=True,
                          timeout=180, env=env)


def sessions(cfg, entries):
    d = cfg / "tmp" / "hardmode"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


# ---- doctor ----

def test_doctor_on_a_fresh_config_dir_warns_but_passes(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    r = run("doctor.py", [], cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN plugin" in r.stdout and "not registered" in r.stdout
    assert "OK   wiring" in r.stdout and "12 hooks wired" in r.stdout
    assert "OK   privacy" in r.stdout and "shipped default" in r.stdout
    assert "WARN witness" in r.stdout
    assert re.search(r"doctor: \d+ ok, \d+ warn, 0 fail", r.stdout)


def test_doctor_strict_fails_on_kill_switches_and_double_wiring(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({
        "disableAllHooks": True, "effortLevel": "xhigh",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 ~/hardmode/hooks/stop-claim-audit.py"}]}]}}))
    r = run("doctor.py", ["--strict"], cfg)
    assert r.returncode == 1
    assert "FAIL kill-switch" in r.stdout and "FAIL double-wiring" in r.stdout


def test_doctor_recognises_a_registered_plugin_and_version_drift(tmp_path):
    cfg = tmp_path / "cfg"
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "hardmode@hardmode": [{"scope": "user", "installPath": "/x/cache/hardmode/2.0.0", "version": "2.0.0"}]}}))
    (cfg / "settings.json").write_text(json.dumps({"enabledPlugins": {"hardmode@hardmode": True}, "effortLevel": "xhigh",
                                                   "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}}))
    r = run("doctor.py", [], cfg)
    assert "WARN plugin" in r.stdout and "claude plugin update hardmode" in r.stdout
    assert "OK   plugin-enabled" in r.stdout and "OK   effortLevel" in r.stdout


def test_doctor_witness_fails_when_hooks_never_ran(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    sessions(cfg, [{"session": f"s{i}", "ended": 1, "by_hook": {}} for i in range(4)])
    r = run("doctor.py", ["--strict"], cfg)
    assert r.returncode == 1 and "FAIL witness" in r.stdout and "did not run" in r.stdout
    sessions(cfg, [{"session": f"s{i}", "ended": 1, "by_hook": {"floor-check:ran": 1, "claim-audit:block": 1}} for i in range(4)])
    r = run("doctor.py", ["--strict"], cfg)
    assert "OK   witness" in r.stdout and "claim-audit:block x4" in r.stdout


def test_doctor_init_privacy_and_json_and_demo(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    r = run("doctor.py", ["--init-privacy", "--json", "--demo"], cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    checks = {row["check"]: row for row in out["rows"]}
    assert checks["privacy-init"]["level"] == "OK" and (cfg / "memory" / "privacy.toml").is_file()
    assert checks["privacy"]["evidence"].startswith("11 pattern(s) from your")
    assert checks["demo"]["level"] == "OK" and "10/10" in checks["demo"]["evidence"]


def test_doctor_detects_broken_wiring(tmp_path):
    import shutil
    plugin = tmp_path / "plugin"
    shutil.copytree(ROOT / "hooks", plugin / "hooks")
    shutil.copytree(ROOT / "doctrine", plugin / "doctrine")
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text('{"name": "hardmode", "version": "9.9.9"}')
    wiring = json.loads((plugin / "hooks" / "hooks.json").read_text())
    wiring["hooks"]["SessionEndz"] = wiring["hooks"].pop("SessionEnd")
    (plugin / "hooks" / "hooks.json").write_text(json.dumps(wiring))
    (plugin / "hooks" / "pretool-destructive-guard.py").write_text("def (broken")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    r = run("doctor.py", ["--strict", "--plugin-root", str(plugin)], cfg)
    assert r.returncode == 1
    assert "FAIL wiring-events" in r.stdout and "SessionEndz" in r.stdout
    assert "FAIL wiring" in r.stdout and "pretool-destructive-guard.py" in r.stdout


# ---- stats ----

def test_stats_reports_firings_and_witnessing(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    sessions(cfg, [
        {"session": "a", "reason": "other", "ended": 2, "events": 3,
         "by_hook": {"floor-check:ran": 1, "claim-audit:block": 1, "destructive-guard:override": 1}},
        {"session": "b", "reason": "clear", "ended": 3, "events": 1, "by_hook": {"floor-check:ran": 1}},
    ])
    (cfg / "tmp" / "hardmode" / "ledger-live.jsonl").write_text(
        json.dumps({"hook": "loop-alarm", "outcome": "nudge"}) + "\n")
    r = run("stats.py", [], cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 ended, 1 live" in r.stdout and "witnessed running in 2/2" in r.stdout
    assert "claim-audit:block x1" in r.stdout and "loop-alarm:nudge x1" in r.stdout and "1 override(s)" in r.stdout
    j = json.loads(run("stats.py", ["--json"], cfg).stdout)
    assert j["sessions_ended"] == 2 and j["sessions_live"] == 1 and j["overrides"] == 1
    assert j["blocks_per_100_sessions"] == round(100.0 * 2 / 3, 1)


def test_stats_warns_when_the_floor_was_never_witnessed(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    sessions(cfg, [{"session": f"s{i}", "ended": 1, "by_hook": {}} for i in range(3)])
    r = run("stats.py", [], cfg)
    assert "never witnessed" in r.stdout and "hooks are not running" in r.stdout


def test_stats_on_an_empty_state_dir(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    r = run("stats.py", [], cfg)
    assert r.returncode == 0 and "0 ended" in r.stdout


# ---- memcheck ----

def test_memcheck_where_and_dupes_and_privacy(tmp_path):
    cfg = tmp_path / "cfg"
    project = tmp_path / "my.repo"
    project.mkdir()
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(project))
    mem = cfg / "projects" / slug / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("- [parser timeout](parser-timeout.md)\n")
    (mem / "parser-timeout.md").write_text("---\nname: parser timeout\ndescription: the parser hangs on empty logs; root cause was the mutable default\n---\nbody\n")
    r = run("memcheck.py", ["--where", "--cwd", str(project)], cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert slug in r.stdout and "topic files:  1" in r.stdout and "mutable default" in r.stdout and "1 non-empty line" in r.stdout
    r = run("memcheck.py", ["--dupes", "empty logs hang the parser", "--cwd", str(project)], cfg)
    assert "parser-timeout.md" in r.stdout and "UPDATE this file" in r.stdout
    r = run("memcheck.py", ["--dupes", "completely unrelated topic", "--cwd", str(project)], cfg)
    assert "new file is appropriate" in r.stdout
    r = run("memcheck.py", ["--privacy", "--cwd", str(project)], cfg)
    assert r.returncode == 0 and "0 hit(s)" in r.stdout
    (mem / "leak.md").write_text("token ghp_abcdef1234\n")
    r = run("memcheck.py", ["--privacy", "--cwd", str(project)], cfg)
    assert r.returncode == 1 and "leak.md:1" in r.stdout


def test_memcheck_only_treats_a_truthy_disable_flag_as_disabled(tmp_path):
    cfg = tmp_path / "cfg"
    project = tmp_path / "proj"
    project.mkdir()
    for v in ("0", "false", "no", "off", ""):
        r = run("memcheck.py", ["--where", "--cwd", str(project)], cfg, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": v})
        assert r.returncode == 0 and "disabled" not in r.stdout.lower(), v
    r = run("memcheck.py", ["--where", "--cwd", str(project)], cfg, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
    assert "disabled" in r.stdout.lower()


def test_stats_since_does_not_count_filtered_out_sessions_as_live(tmp_path):
    import time
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    now = time.time()
    sessions(cfg, [
        {"session": "old", "reason": "other", "ended": now - 10 * 86400, "events": 1, "by_hook": {"floor-check:ran": 1}},
        {"session": "new", "reason": "other", "ended": now - 60, "events": 1, "by_hook": {"floor-check:ran": 1}},
    ])
    (cfg / "tmp" / "hardmode" / "ledger-old.jsonl").write_text(json.dumps({"hook": "floor-check", "outcome": "ran"}) + "\n")
    j = json.loads(run("stats.py", ["--json", "--since", "1"], cfg).stdout)
    assert j["sessions_ended"] == 1 and j["sessions_live"] == 0
    j = json.loads(run("stats.py", ["--json"], cfg).stdout)
    assert j["sessions_ended"] == 2 and j["sessions_live"] == 0


def test_doctor_double_wiring_is_detected_by_hook_basename(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 /opt/kits/guards/pretool-destructive-guard.py"}]}]}}))
    r = run("doctor.py", ["--strict"], cfg)
    assert "FAIL double-wiring" in r.stdout and "pretool-destructive-guard.py" in r.stdout
    (cfg / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 /opt/kits/guards/my-own-guard.py"}]}]}}))
    assert "double-wiring" not in run("doctor.py", ["--strict"], cfg).stdout


def test_doctor_notes_when_it_runs_from_the_installed_snapshot(tmp_path):
    # /hardmode:doctor runs the copy inside the plugin cache; from there, drift against
    # the operator's clone is not checkable and doctor must say so instead of "OK".
    import shutil
    cfg = tmp_path / "cfg"
    snap = tmp_path / "cache" / "hardmode" / "3.1.0"
    shutil.copytree(ROOT, snap, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__", ".pytest_cache", "bench"))
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "hardmode@hardmode": [{"scope": "user", "installPath": str(snap), "version": version}]}}))
    (cfg / "settings.json").write_text(json.dumps({"enabledPlugins": {"hardmode@hardmode": True}}))
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg), HARDMODE_STATE_DIR=str(cfg / "tmp" / "hardmode"), CLAUDE_PLUGIN_ROOT=str(snap))
    r = subprocess.run([sys.executable, str(snap / "tools" / "doctor.py")], capture_output=True, text=True, timeout=180, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "running from the installed snapshot" in r.stdout and "drift against your clone is not" in r.stdout
    # the same registration seen from the clone is a plain OK (versions match)
    r = run("doctor.py", [], cfg)
    assert "installed snapshot" not in r.stdout and "OK   plugin " in r.stdout


# ---- commands ----

def test_commands_have_frontmatter_and_run_shipped_tools():
    cmds = sorted((ROOT / "commands").glob("*.md"))
    assert {c.name for c in cmds} == {"doctor.md", "stats.md", "selftest.md"}
    for c in cmds:
        text = c.read_text(encoding="utf-8")
        fm = re.match(r"---\n(.*?)\n---\n", text, re.S)
        assert fm and "description:" in fm.group(1) and "allowed-tools: Bash(python3:*)" in fm.group(1), c.name
        m = re.search(r"!`python3 \"\$\{CLAUDE_PLUGIN_ROOT\}/(tools/[a-z]+\.py)\"", text)
        assert m and (ROOT / m.group(1)).is_file(), c.name
