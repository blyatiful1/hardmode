#!/usr/bin/env python3
"""hardmode doctor — verify the install does what the docs say (stdlib only).

The kit's own history has two instances of "the deterministic floor was silently
inert for weeks under a green report". This checks the things that make that
happen, from the outside in:

  python      version, tomllib availability
  cli         `claude` on PATH and its version (workflows need >= 2.1.154)
  plugin      registered in <config dir>/plugins (installed_plugins.json or the
              synced layout), enabled in settings.json, version vs this checkout
  wiring      hooks/hooks.json: known events only, every script present + compiles,
              every shipped hook wired
  settings    effortLevel / output-token env present; the three kill switches that
              disable hooks (disableAllHooks, allowManagedHooksOnly, a duplicate
              hook wiring in settings.json that double-fires)
  doctrine    the machine-wide CLAUDE.md carries the doctrine
  privacy     which privacy.toml is in force and how many patterns it holds
  state       the state dir is writable
  witness     recent sessions in which the floor was actually seen running
              (a session without a floor-check record = hooks did not run)
  demo        --demo: run tools/demo.py (the real hooks against planted failures)

Usage: doctor.py [--strict] [--demo] [--init-privacy] [--json] [--plugin-root DIR]
Exit 0, or 1 under --strict when any check FAILs.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hooks"))
from _hardmode import config_dir, iter_jsonl, state_dir  # noqa: E402

KNOWN_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Notification", "UserPromptSubmit",
                "SessionStart", "SessionEnd", "Stop", "SubagentStart", "SubagentStop", "PreCompact",
                "PermissionRequest", "Setup", "TeammateIdle", "TaskCompleted"}
MIN_WORKFLOW_VERSION = (2, 1, 154)


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, check, evidence):
        self.rows.append({"level": level, "check": check, "evidence": evidence})

    def ok(self, check, evidence):
        self.add("OK", check, evidence)

    def warn(self, check, evidence):
        self.add("WARN", check, evidence)

    def fail(self, check, evidence):
        self.add("FAIL", check, evidence)

    def count(self, level):
        return sum(1 for r in self.rows if r["level"] == level)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def plugin_version(root):
    m = read_json(os.path.join(root, ".claude-plugin", "plugin.json")) or {}
    return m.get("version", "?")


def check_python(r):
    v = sys.version_info
    if v < (3, 8):
        r.fail("python", f"{sys.version.split()[0]} is too old (need >= 3.8)")
    else:
        r.ok("python", f"{sys.version.split()[0]} at {sys.executable}")
    try:
        import tomllib  # noqa: F401
        r.ok("tomllib", "available — privacy.toml parsed natively")
    except ImportError:
        r.warn("tomllib", "not available (< 3.11) — the privacy guard uses its minimal parser; fine for the shipped shape")


def check_cli(r):
    exe = shutil.which("claude")
    if not exe:
        r.warn("cli", "`claude` not on PATH — cannot check the harness version (hooks still run inside sessions)")
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15).stdout
    except Exception as e:
        r.warn("cli", f"`claude --version` failed: {e}")
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    if not m:
        r.warn("cli", f"could not parse version from {out.strip()!r}")
        return None
    ver = tuple(int(x) for x in m.groups())
    real = os.path.realpath(exe)
    if ver < MIN_WORKFLOW_VERSION:
        r.warn("cli", f"Claude Code {'.'.join(map(str, ver))} at {real} — saved workflows need >= 2.1.154; hooks/agents/skills work")
    else:
        r.ok("cli", f"Claude Code {'.'.join(map(str, ver))} at {real}")
    return ver


def check_registration(r, root):
    cfg = config_dir()
    # The checkout's version is the one THIS file ships with (module-relative ROOT);
    # `root` may be the installed snapshot when run as /hardmode:doctor.
    src_version = plugin_version(ROOT)
    from_snapshot = os.path.realpath(root) != os.path.realpath(ROOT)
    found = []
    installed = read_json(os.path.join(cfg, "plugins", "installed_plugins.json")) or {}
    for key, entries in (installed.get("plugins") or {}).items():
        if key.split("@")[0] == "hardmode" and isinstance(entries, list):
            for e in entries:
                found.append((key, e.get("version", "?"), e.get("installPath", "?"), e.get("scope", "?")))
    synced = [p for p in glob.glob(os.path.join(cfg, "plugins", "synced", "*", "*"))
              if os.path.basename(p).startswith("hardmode")]
    settings = read_json(os.path.join(cfg, "settings.json")) or {}
    enabled = {k: v for k, v in (settings.get("enabledPlugins") or {}).items() if k.split("@")[0] == "hardmode"}
    if found:
        for key, ver, path, scope in found:
            note = f"{key} v{ver} ({scope}) at {path}"
            installed_here = os.path.realpath(path) == os.path.realpath(ROOT) if isinstance(path, str) else False
            if installed_here:
                r.ok("plugin", note + " — running from the installed snapshot; drift against your clone is not "
                                "checkable from here (run `python3 tools/doctor.py` inside the clone)")
            elif ver != src_version:
                r.warn("plugin", f"{note} — this checkout is v{src_version}: run `claude plugin update hardmode` (the install is a pinned snapshot, not a live link)")
            else:
                r.ok("plugin", note)
        if enabled and not all(enabled.values()):
            r.fail("plugin-enabled", f"disabled in settings.json enabledPlugins: {enabled}")
        elif not enabled:
            r.warn("plugin-enabled", "no enabledPlugins entry for hardmode in settings.json — the harness may still load it; verify with `claude plugin list`")
        else:
            r.ok("plugin-enabled", ", ".join(enabled))
    elif synced:
        r.ok("plugin", f"synced install: {synced[0]} (managed by the remote/cowork host)")
    elif os.environ.get("CLAUDE_PLUGIN_ROOT") or from_snapshot:
        r.ok("plugin", f"running under plugin root {root}")
    else:
        r.warn("plugin", f"hardmode is not registered under {cfg}/plugins — install with "
                         "`claude plugin marketplace add <checkout> && claude plugin install hardmode@hardmode` "
                         "(or set CLAUDE_CONFIG_DIR to the config dir you actually use)")


def check_wiring(r, root):
    hooks_dir = os.path.join(root, "hooks")
    wiring = read_json(os.path.join(hooks_dir, "hooks.json"))
    if not isinstance(wiring, dict) or "hooks" not in wiring:
        r.fail("wiring", "hooks/hooks.json missing or not valid JSON")
        return
    unknown = set(wiring["hooks"]) - KNOWN_EVENTS
    if unknown:
        r.fail("wiring-events", f"unknown events (ignored at runtime): {sorted(unknown)}")
    wired, broken = set(), []
    for event, groups in wiring["hooks"].items():
        for g in groups:
            for h in g.get("hooks", []):
                name = h.get("command", "").rstrip('"').split("/")[-1]
                wired.add(name)
                path = os.path.join(hooks_dir, name)
                if not os.path.isfile(path):
                    broken.append(f"{event}: {name} missing")
                    continue
                try:
                    with open(path, encoding="utf-8") as f:
                        compile(f.read(), path, "exec")
                except SyntaxError as e:
                    broken.append(f"{name}: line {e.lineno}: {e.msg}")
    shipped = {f for f in os.listdir(hooks_dir) if f.endswith(".py") and not f.startswith("_")}
    for name in sorted(shipped - wired):
        broken.append(f"{name} ships but is not wired")
    if broken:
        r.fail("wiring", "; ".join(broken))
    else:
        r.ok("wiring", f"{len(wired)} hooks wired across {len(wiring['hooks'])} events; all present and compile")


def check_settings(r):
    cfg = config_dir()
    path = os.path.join(cfg, "settings.json")
    s = read_json(path)
    if s is None:
        r.warn("settings", f"{path} missing or invalid — effortLevel and the output-token env are not set")
        return
    if s.get("disableAllHooks") is True:
        r.fail("kill-switch", "settings.json disableAllHooks=true — EVERY hook is off; the floor is inert")
    if (s.get("permissions") or {}).get("allowManagedHooksOnly") or s.get("allowManagedHooksOnly"):
        r.fail("kill-switch", "allowManagedHooksOnly is set — plugin hooks are skipped")
    shipped = {f for f in os.listdir(os.path.join(ROOT, "hooks")) if f.endswith(".py") and not f.startswith("_")}
    dup = []
    for groups in (s.get("hooks") or {}).values():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                name = cmd.rstrip('"\'').split("/")[-1]
                if name in shipped:
                    dup.append(name)
    if dup:
        r.fail("double-wiring", f"settings.json also wires the plugin's hooks ({', '.join(sorted(set(dup)))}) — every event fires twice; remove them, the plugin owns the wiring")
    if s.get("effortLevel") in ("xhigh", "high"):
        r.ok("effortLevel", s["effortLevel"])
    else:
        r.warn("effortLevel", f"{s.get('effortLevel')!r} — doctrine/settings-snippet.json recommends xhigh")
    env = s.get("env") or {}
    if env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS"):
        r.ok("max-output-tokens", env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"])
    else:
        r.warn("max-output-tokens", "CLAUDE_CODE_MAX_OUTPUT_TOKENS not set in settings.json env (see doctrine/settings-snippet.json)")


def check_doctrine(r):
    path = os.path.join(config_dir(), "CLAUDE.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        r.warn("doctrine", f"{path} missing — copy doctrine/CLAUDE.md there and fill in '## This machine'")
        return
    if "Evidence before claims" in text:
        note = " ('## This machine' still holds the placeholder comment)" if "Replace with 3-6 lines" in text else ""
        r.ok("doctrine", f"{path} carries the doctrine{note}")
    else:
        r.warn("doctrine", f"{path} does not carry the hardmode doctrine (no 'Evidence before claims' section)")


def check_privacy(r, root, init):
    import importlib.util
    spec = importlib.util.spec_from_file_location("mem_guard", os.path.join(root, "hooks", "pretool-mem-privacy-guard.py"))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    user = os.path.join(config_dir(), "memory", "privacy.toml")
    shipped = os.path.join(root, "doctrine", "privacy.toml")
    if init and not os.path.exists(user):
        os.makedirs(os.path.dirname(user), exist_ok=True)
        shutil.copyfile(shipped, user)
        r.ok("privacy-init", f"copied the shipped patterns to {user} — add your work markers there")
    pats, source = guard.load_patterns()
    if not pats:
        r.fail("privacy", "no patterns anywhere — the memory privacy guard is inert (doctrine/privacy.toml missing?)")
    elif source == user:
        r.ok("privacy", f"{len(pats)} pattern(s) from your {user}")
    else:
        r.ok("privacy", f"{len(pats)} shipped default pattern(s) from {source}; run --init-privacy to add your own work markers")


def check_state_and_witness(r):
    d = state_dir()
    probe = os.path.join(d, ".doctor-probe")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.unlink(probe)
        r.ok("state-dir", d)
    except OSError as e:
        r.fail("state-dir", f"{d} not writable ({e}) — stateful hooks (loop alarm, compaction save, ledger) fail open")
        return
    sessions = list(iter_jsonl(os.path.join(d, "sessions.jsonl")))
    if not sessions:
        r.warn("witness", "no completed sessions recorded yet — the floor has not been observed running (start and end one session)")
        return
    recent = sessions[-10:]
    witnessed = sum(1 for s in recent if (s.get("by_hook") or {}).get("floor-check:ran"))
    fired = {}
    for s in sessions:
        for k, v in (s.get("by_hook") or {}).items():
            if k.split(":")[-1] in ("block", "nudge", "deny", "deny-edit"):
                fired[k] = fired.get(k, 0) + v
    summary = f"{len(sessions)} session(s) recorded; floor witnessed in {witnessed}/{len(recent)} recent; fired: " + \
              (", ".join(f"{k} x{v}" for k, v in sorted(fired.items())) or "nothing yet")
    if len(recent) >= 3 and witnessed == 0:
        r.fail("witness", summary + " — hooks did not run in any recent session (plugin disabled? disableAllHooks? workspace trust?)")
    else:
        r.ok("witness", summary)


def check_demo(r, root):
    try:
        p = subprocess.run([sys.executable, os.path.join(root, "tools", "demo.py"), "--quiet"],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        r.fail("demo", f"could not run: {e}")
        return
    summary = next((ln for ln in p.stdout.splitlines() if ln.startswith("demo:")), p.stdout.strip()[-120:])
    if p.returncode == 0:
        r.ok("demo", summary)
    else:
        fails = " | ".join(ln.strip() for ln in p.stdout.splitlines() if "[FAIL]" in ln)[:400]
        r.fail("demo", f"{summary} — {fails}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify the hardmode install")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--demo", action="store_true", help="also run the live hook self-test")
    ap.add_argument("--init-privacy", action="store_true", help="copy the shipped privacy.toml to the config dir if absent")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--plugin-root", default=os.environ.get("CLAUDE_PLUGIN_ROOT") or ROOT)
    a = ap.parse_args(argv)
    root = a.plugin_root
    r = Report()
    check_python(r)
    check_cli(r)
    check_registration(r, root)
    check_wiring(r, root)
    check_settings(r)
    check_doctrine(r)
    check_privacy(r, root, a.init_privacy)
    check_state_and_witness(r)
    if a.demo:
        check_demo(r, root)
    summary = f"doctor: {r.count('OK')} ok, {r.count('WARN')} warn, {r.count('FAIL')} fail (plugin v{plugin_version(root)}, config {config_dir()})"
    if a.json:
        print(json.dumps({"rows": r.rows, "summary": summary}, indent=1))
    else:
        for row in r.rows:
            print(f"{row['level']:4} {row['check']} — {row['evidence']}")
        print(summary)
    return 1 if (a.strict and r.count("FAIL")) else 0


if __name__ == "__main__":
    sys.exit(main())
