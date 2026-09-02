#!/usr/bin/env python3
"""PreToolUse pre-flight lint for Workflow scripts (hardmode).

A Workflow run spawns many agents on the user's money; a script that fails the kit's
rules (an agent() without a model pin, Date.now()/Math.random() that break resume, a
bad agentType that throws at spawn time, a phase title not in meta.phases) is
cheaper to reject BEFORE it runs than to debug after. The Workflow tool receives the
script text in tool_input.script; this hook hands it to tools/check-workflows.mjs
(the same linter CI runs) and DENIES the call (exit 2) with the linter's findings.

Saved workflows (invoked by name/scriptPath) are linted in CI already and pass
through. Needs `node`; without it, or on any error, the hook fails open.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hardmode import ledger, reconfigure_utf8  # noqa: E402

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    reconfigure_utf8(sys.stdin, sys.stderr)
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Workflow":
        return 0
    tool_input = data.get("tool_input") or {}
    script = tool_input.get("script") if isinstance(tool_input, dict) else None
    if not isinstance(script, str) or not script.strip():
        return 0
    node = shutil.which("node")
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or PLUGIN_ROOT
    linter = os.path.join(root, "tools", "check-workflows.mjs")
    if not node or not os.path.isfile(linter):
        return 0
    with tempfile.TemporaryDirectory(prefix="hardmode-wf-") as td:
        path = os.path.join(td, "inline-workflow.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        try:
            p = subprocess.run([node, linter, "--script", path], capture_output=True,
                               text=True, timeout=20)
        except Exception:
            return 0
    if p.returncode != 1:
        return 0      # 0 = clean; 2 = the linter itself crashed — never blame the script
    findings = "\n".join(ln for ln in (p.stderr + p.stdout).splitlines() if ln.strip())[:2000]
    print("WORKFLOW LINT (automated): this script breaks the kit's workflow rules and was not "
          "run. Fix and resubmit:\n" + findings, file=sys.stderr)
    ledger(data, "workflow-lint", "deny", findings.splitlines()[0][:80] if findings else "")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
