# Unit tests for the PreToolUse destructive-command guard.
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "claude" / "hooks" / "pretool-destructive-guard.py"


def run_hook(command, cwd=None, tool_name="Bash", raw_stdin=None):
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30,
    )


def make_repo(tmp_path, dirty):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    if dirty:
        (repo / "work.txt").write_text("uncommitted")
    return repo


def test_reset_hard_blocked_on_dirty_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    r = run_hook("git reset --hard HEAD~1", cwd=repo)
    assert r.returncode == 2
    assert "DESTRUCTIVE COMMAND GUARD" in r.stderr


def test_reset_hard_allowed_on_clean_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git reset --hard HEAD~1", cwd=repo).returncode == 0


def test_checkout_discard_blocked_on_dirty_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git checkout -- .", cwd=repo).returncode == 2
    assert run_hook("git checkout .", cwd=repo).returncode == 2
    # CONF4: `git checkout ./` and `git checkout ..` are the same tree-destroyer.
    assert run_hook("git checkout ./", cwd=repo).returncode == 2
    assert run_hook("git checkout ..", cwd=repo).returncode == 2


def test_checkout_branch_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git checkout -b feature/x", cwd=repo).returncode == 0
    assert run_hook("git checkout main", cwd=repo).returncode == 0


def test_restore_blocked_but_staged_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git restore src/", cwd=repo).returncode == 2
    assert run_hook("git restore --staged src/", cwd=repo).returncode == 0
    assert run_hook("git restore --staged --worktree src/", cwd=repo).returncode == 2


def test_clean_blocked_on_dirty_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git clean -fd", cwd=repo).returncode == 2


def test_stash_drop_blocked_unconditionally(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git stash drop", cwd=repo).returncode == 2
    assert run_hook("git stash clear", cwd=repo).returncode == 2
    assert run_hook("git stash push -u", cwd=repo).returncode == 0


def test_force_push_blocked_lease_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git push --force origin main", cwd=repo).returncode == 2
    assert run_hook("git push -f origin main", cwd=repo).returncode == 2
    assert run_hook("git push --force-with-lease origin main", cwd=repo).returncode == 0
    assert run_hook("git push -u origin main", cwd=repo).returncode == 0


def test_force_with_lease_elsewhere_does_not_excuse_bare_force(tmp_path):
    # CONF3: --force-with-lease in a DIFFERENT segment (a chained safe push, an echo)
    # must not suppress the block on a bare --force in its own segment.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook(
        'git push --force origin main && echo "prefer --force-with-lease next time"',
        cwd=repo).returncode == 2
    assert run_hook(
        "git push --force-with-lease origin a && git push --force origin b",
        cwd=repo).returncode == 2


def test_plus_refspec_force_push_blocked(tmp_path):
    # `git push origin +main` IS a force-push — the + evades a flag-only check.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git push origin +main", cwd=repo).returncode == 2
    assert run_hook("git push origin +refs/heads/main", cwd=repo).returncode == 2
    assert run_hook("git push origin main", cwd=repo).returncode == 0
    assert run_hook("git push origin HEAD:main", cwd=repo).returncode == 0


def test_switch_discard_blocked_on_dirty_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git switch -f main", cwd=repo).returncode == 2
    assert run_hook("git switch --discard-changes main", cwd=repo).returncode == 2
    assert run_hook("git switch main", cwd=repo).returncode == 0
    assert run_hook("git switch -c feature/x", cwd=repo).returncode == 0


def test_switch_discard_allowed_on_clean_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git switch -f main", cwd=repo).returncode == 0


def test_catastrophic_rm_blocked():
    for cmd in ("rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf .", "rm -rf ..",
                "rm -rf *", "rm -r -f /", "rm -r .", "rm -Rf $HOME"):
        assert run_hook(cmd).returncode == 2, cmd


def test_scoped_rm_allowed():
    for cmd in ("rm -rf build/", "rm -rf /tmp/scratch", "rm -rf node_modules",
                "rm file.txt", "rm -f *.pyc"):
        assert run_hook(cmd).returncode == 0, cmd


def test_mentions_inside_quotes_do_not_trip(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('git commit -m "guard git reset --hard in hook"', cwd=repo).returncode == 0
    assert run_hook('echo "never run git stash clear blindly" >> notes.md', cwd=repo).returncode == 0


def test_quoted_rm_target_still_blocked():
    assert run_hook('rm -rf "."').returncode == 2
    assert run_hook("rm -rf '/'").returncode == 2


def test_override_token_allows(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("FABLE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0
    # Also valid as a segment-leading assignment after a separator.
    assert run_hook("cd repo; FABLE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0


def test_override_only_as_assignment_not_mere_mention(tmp_path):
    # CONF5: the override string inside a quoted commit message (or any non-assignment
    # position) must NOT disable the guard for the rest of the command.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook(
        'git commit -m "set FABLE_DESTRUCTIVE_OK=1 to bypass" && git reset --hard',
        cwd=repo).returncode == 2


def test_non_git_cwd_fails_open(tmp_path):
    assert run_hook("git reset --hard", cwd=tmp_path).returncode == 0


def test_non_bash_tool_ignored():
    assert run_hook("git reset --hard", tool_name="Edit").returncode == 0


def test_malformed_stdin_fails_open():
    assert run_hook("", raw_stdin="not json").returncode == 0
