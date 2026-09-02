# Unit tests for the PreToolUse read-only enforcement of the verification agents.
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "pretool-readonly-agent.py"


def run_hook(tmp_path, command=None, tool="Bash", agent="hardmode:verifier", tool_input=None, env_extra=None):
    payload = {"tool_name": tool, "hook_event_name": "PreToolUse", "session_id": "ro",
               "cwd": "/home/user/proj", "scratchpad_dir": str(tmp_path / "scratch")}
    if agent is not None:
        payload["agent_type"] = agent
        payload["agent_id"] = "a1"
    payload["tool_input"] = tool_input if tool_input is not None else {"command": command}
    env = dict(os.environ, HARDMODE_STATE_DIR=str(tmp_path / "state"))
    env.pop("HARDMODE_READONLY_AGENTS", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30, env=env)


def test_main_thread_and_other_agents_are_untouched(tmp_path):
    assert run_hook(tmp_path, "echo x > /home/user/proj/a.py", agent=None).returncode == 0
    assert run_hook(tmp_path, "echo x > /home/user/proj/a.py", agent="general-purpose").returncode == 0
    assert run_hook(tmp_path, "echo x > /home/user/proj/a.py", agent="Explore").returncode == 0


def test_tree_writes_are_denied_for_verification_agents(tmp_path):
    for agent in ("hardmode:verifier", "verifier", "hardmode:plan-critic", "hardmode:oracle", "hardmode:scout"):
        r = run_hook(tmp_path, "echo x > /home/user/proj/a.py", agent=agent)
        assert r.returncode == 2 and "READ-ONLY AGENT" in r.stderr, agent
    for cmd in ("sed -i 's/a/b/' src/x.py", "git commit -m x", "git add -A", "git checkout -- .",
                "git stash", "git reset --hard", "rm -rf build/", "mv a.py b.py", "touch src/new.py",
                "black src/", "npm install left-pad", "cargo add serde", "printf 'x' >> notes.md",
                "find . -name '*.pyc' -delete", "git ls-files | xargs rm -f", "tee out.txt",
                "python3 -c 'print(1)' > result.txt"):
        assert run_hook(tmp_path, cmd).returncode == 2, cmd


def test_reads_and_checks_are_allowed(tmp_path):
    for cmd in ("git status", "git diff HEAD", "git log --oneline -5", "git show HEAD:x.py",
                "pytest -q", "python3 -m pytest tests/ -q 2>&1 | tail -5", "npm test", "cargo test",
                "grep -rn foo src/", "cat x.py", "ls -la", "make check", "./verify.sh",
                "pytest -q > /dev/null 2>&1", "awk '$3 > 100' log.txt", "git stash list",
                "pip install pytest", "uv sync", "npm ci", "git fetch origin", "git branch -a",
                "echo 'a -> b'", "diff <(sort a) <(sort b)", "ls 2>&1"):
        assert run_hook(tmp_path, cmd).returncode == 0, cmd


def test_scratch_writes_are_allowed(tmp_path):
    scratch = tmp_path / "scratch"
    for cmd in (f"pytest -q > {scratch}/out.log 2>&1", f"pytest --junitxml={scratch}/r.xml",
                f"cp src/x.py {scratch}/x.py", f"mkdir -p {scratch}/probe", f"tee {scratch}/log.txt",
                "pytest -q > /tmp/out.log", "cat x > /tmp/probe/y", "rm -rf /tmp/probe"):
        assert run_hook(tmp_path, cmd).returncode == 0, cmd
    assert run_hook(tmp_path, f"cp {scratch}/x.py src/x.py").returncode == 2


def test_editing_tools_are_denied_even_if_available(tmp_path):
    for tool in ("Edit", "Write", "NotebookEdit"):
        assert run_hook(tmp_path, tool=tool, tool_input={"file_path": "x.py"}).returncode == 2
    assert run_hook(tmp_path, tool="Read", tool_input={"file_path": "x.py"}).returncode == 0


def test_extra_agents_via_env(tmp_path):
    assert run_hook(tmp_path, "rm -rf build/", agent="myplugin:auditor").returncode == 0
    r = run_hook(tmp_path, "rm -rf build/", agent="myplugin:auditor",
                 env_extra={"HARDMODE_READONLY_AGENTS": "auditor,other"})
    assert r.returncode == 2


def test_denials_are_ledgered_and_malformed_input_fails_open(tmp_path):
    run_hook(tmp_path, "git commit -m x")
    recs = [json.loads(ln) for ln in (tmp_path / "state" / "ledger-ro.jsonl").read_text().splitlines()]
    assert any(r["hook"] == "readonly-agent" and r["outcome"] == "deny" for r in recs)
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0


def test_multi_line_commands_are_judged_after_a_newline(tmp_path):
    for cmd in ("ls\nrm -rf src", "git status\ngit add -A", "set -e\nsed -i 's/a/b/' x.py", "true\n\necho x > a.py"):
        assert run_hook(tmp_path, cmd).returncode == 2, cmd
    assert run_hook(tmp_path, "ls\ngit status\necho 'rm -rf src'").returncode == 0


def test_quoted_paths_are_one_token(tmp_path):
    scratch = tmp_path / "scratch"
    assert run_hook(tmp_path, f'echo x > "{scratch}/my file.txt"').returncode == 0
    assert run_hook(tmp_path, f"echo x > '{scratch}/my file.txt'").returncode == 0
    assert run_hook(tmp_path, 'echo x > "/home/user/proj/my file.txt"').returncode == 2
    assert run_hook(tmp_path, f'cp "src/a b.py" "{scratch}/copy.py"').returncode == 0
    assert run_hook(tmp_path, f'cp "{scratch}/copy.py" "src/a b.py"').returncode == 2
    assert run_hook(tmp_path, "awk '$3 > 100 {print}' log.txt | sort").returncode == 0
    assert run_hook(tmp_path, 'grep ">" file.txt').returncode == 0


def test_file_ops_judge_the_destination_only(tmp_path):
    scratch = tmp_path / "scratch"
    for cmd in (f"cp src/a.py {scratch}/a.py", f"mv {scratch}/a {scratch}/b", f"dd if=/dev/zero of={scratch}/img bs=1M count=1",
                f"install -m 644 src/a.py {scratch}/", f"ln -s src/a.py {scratch}/link", f"mkdir -p {scratch}/sub",
                f"touch {scratch}/marker", "git worktree list", "git tag -l", "git stash show -p"):
        assert run_hook(tmp_path, cmd).returncode == 0, cmd
    for cmd in (f"cp {scratch}/a.py src/a.py", "dd if=/dev/zero of=./img", f"mv {scratch}/a ./a", "ln -s x ./link",
                "git tag v1", "git tag -d v1", "git worktree add ../wt", "git stash pop"):
        assert run_hook(tmp_path, cmd).returncode == 2, cmd
