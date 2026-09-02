# Unit tests for the PreToolUse destructive-command guard (run as a real subprocess).
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "pretool-destructive-guard.py"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    # Every test gets its own state dir: the guard's ledger must never land in the
    # operator's real ~/.claude/tmp/hardmode, nor in a shared /tmp path that a
    # parallel run could race on.
    monkeypatch.setenv("HARDMODE_STATE_DIR", str(tmp_path / "guard-state"))


def run_hook(command, cwd=None, tool_name="Bash", raw_stdin=None, state_dir=None, extra=None,
             env_extra=None, proc_cwd=None):
    payload = {"tool_name": tool_name, "tool_input": {"command": command},
               "hook_event_name": "PreToolUse", "session_id": "guard-test"}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    if extra:
        payload.update(extra)
    env = dict(os.environ)
    env.pop("HARDMODE_DESTRUCTIVE_OK", None)
    if state_dir:
        env["HARDMODE_STATE_DIR"] = str(state_dir)
    assert "HARDMODE_STATE_DIR" in env
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True, text=True, timeout=30, env=env, cwd=proc_cwd,
    )


HERMETIC_GIT = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                    GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")


def git(repo, *args):
    # Isolated from the operator's global git config (commit.gpgsign, hooksPath, ...).
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, check=True,
                   capture_output=True, env=HERMETIC_GIT)


def make_repo(tmp_path, dirty, name="repo"):
    """A repo with one commit. dirty=True adds an untracked file at the root."""
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "tracked.txt").write_text("committed\n")
    (repo / ".gitignore").write_text("build/\nnode_modules/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    if dirty:
        (repo / "work.txt").write_text("uncommitted")
    return repo


# ---- tree destroyers (blocked only on a dirty tree) ---------------------------------

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
    for cmd in ("git checkout -- .", "git checkout .", "git checkout ./", "git checkout ..",
                "git checkout -f main", "git checkout --force main", "git checkout -qf main",
                "git checkout -fq HEAD"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd


def test_checkout_branch_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git checkout -b feature/x", cwd=repo).returncode == 0
    assert run_hook("git checkout main", cwd=repo).returncode == 0


def test_scoped_checkout_judges_only_the_named_paths(tmp_path):
    # `git checkout -- tracked.txt` on an UNMODIFIED file discards nothing, even though
    # an unrelated untracked file makes the tree dirty; a modified file still blocks.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git checkout -- tracked.txt", cwd=repo).returncode == 0
    (repo / "tracked.txt").write_text("edited\n")
    assert run_hook("git checkout -- tracked.txt", cwd=repo).returncode == 2


def test_restore_blocked_but_staged_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("new")
    assert run_hook("git restore src/", cwd=repo).returncode == 2
    assert run_hook("git restore --staged src/", cwd=repo).returncode == 0
    assert run_hook("git restore -S src/", cwd=repo).returncode == 0   # short form of --staged
    assert run_hook("git restore --staged --worktree src/", cwd=repo).returncode == 2
    assert run_hook("git restore -S -W src/", cwd=repo).returncode == 2
    # a path with nothing to lose passes even on a dirty tree
    assert run_hook("git restore tracked.txt", cwd=repo).returncode == 0


def test_clean_blocked_on_dirty_tree_in_every_spelling(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    for cmd in ("git clean -fd", "git clean -df", "git clean -f", "git clean --force -d",
                "git clean -d --force", "git clean -xd --force"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("git clean -n", cwd=repo).returncode == 0
    assert run_hook("git clean --dry-run -d", cwd=repo).returncode == 0


def test_switch_discard_blocked_on_dirty_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    for cmd in ("git switch -f main", "git switch --force main", "git switch --discard-changes main"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("git switch main", cwd=repo).returncode == 0
    assert run_hook("git switch -c feature/x", cwd=repo).returncode == 0


def test_switch_discard_allowed_on_clean_tree(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git switch -f main", cwd=repo).returncode == 0


# ---- always dangerous ----------------------------------------------------------------

def test_stash_drop_blocked_unconditionally(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git stash drop", cwd=repo).returncode == 2
    assert run_hook("git stash clear", cwd=repo).returncode == 2
    assert run_hook("git stash push -u", cwd=repo).returncode == 0
    assert run_hook("git stash list", cwd=repo).returncode == 0


def test_force_push_blocked_lease_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("git push --force origin main", "git push -f origin main",
                "git push -uf origin main", "git push -fu origin main", "git push -qf origin main"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("git push --force-with-lease origin main", cwd=repo).returncode == 0
    assert run_hook("git push --force-with-lease=main:abc origin main", cwd=repo).returncode == 0
    assert run_hook("git push -u origin main", cwd=repo).returncode == 0
    assert run_hook("git push --set-upstream origin feature", cwd=repo).returncode == 0


def test_force_overrides_lease_in_same_segment(tmp_path):
    # git documents that --force overrides --force-with-lease; the lease must not excuse it.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git push --force-with-lease --force origin main", cwd=repo).returncode == 2


def test_force_with_lease_elsewhere_does_not_excuse_bare_force(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook('git push --force origin main && echo "prefer --force-with-lease next time"',
                    cwd=repo).returncode == 2
    assert run_hook("git push --force-with-lease origin a && git push --force origin b",
                    cwd=repo).returncode == 2


def test_plus_refspec_force_push_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git push origin +main", cwd=repo).returncode == 2
    assert run_hook("git push origin +refs/heads/main", cwd=repo).returncode == 2
    assert run_hook("git push origin main", cwd=repo).returncode == 0
    assert run_hook("git push origin HEAD:main", cwd=repo).returncode == 0


def test_force_push_dry_run_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("git push --dry-run --force origin main", cwd=repo).returncode == 0
    assert run_hook("git push -n --force origin main", cwd=repo).returncode == 0


def test_remote_branch_deletion_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("git push origin --delete feature", "git push --delete origin feature",
                "git push -d origin feature", "git push origin :feature"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("git push origin --dry-run --delete feature", cwd=repo).returncode == 0


def test_history_destroying_git_ops_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("git reflog expire --expire=now --all", "git reflog expire --expire-unreachable=now --all",
                "git gc --prune=now --aggressive", "git gc --prune=all",
                "git update-ref -d refs/heads/main", "git worktree remove --force ../wt",
                "git worktree remove -f ../wt", "shred -u secrets.env", "sudo shred -zvu -n 10 /dev/sda"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    for cmd in ("git reflog", "git gc", "git gc --auto", "git worktree remove ../wt",
                "git worktree list", "git update-ref refs/heads/x HEAD"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd


def test_branch_D_blocked_only_when_unmerged(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    git(repo, "checkout", "-q", "-b", "merged-branch")
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "-b", "unmerged-branch")
    (repo / "only-here.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "unmerged work")
    git(repo, "checkout", "-q", "main")
    assert run_hook("git branch -D unmerged-branch", cwd=repo).returncode == 2
    assert run_hook("git branch --delete --force unmerged-branch", cwd=repo).returncode == 2
    assert run_hook("git branch -D merged-branch", cwd=repo).returncode == 0
    assert run_hook("git branch -d unmerged-branch", cwd=repo).returncode == 0   # git refuses on its own


# ---- rm --------------------------------------------------------------------------------

def test_catastrophic_rm_blocked():
    for cmd in ("rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf .", "rm -rf ..",
                "rm -rf *", "rm -r -f /", "rm -r .", "rm -Rf $HOME", "rm -rf ~/*",
                "rm -rf $HOME/*", "rm -rf ${HOME}/*", "rm -rf ./*", "rm -rf ../*",
                "rm --recursive --force /", "rm --recursive /", "rm -rf -- /",
                "rm -rfvi /", "rm -Rfiv /", "rm -fvir /"):
        assert run_hook(cmd).returncode == 2, cmd


def test_scoped_rm_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("rm -rf build/", "rm -rf /tmp/scratch", "rm -rf node_modules",
                "rm file.txt", "rm -f *.pyc", "rm -rf build/ dist/ node_modules/",
                "rm --recursive build/", "rm -rf ~/projects/*", "rm -rf build/*",
                "rm -f *", "rm -rf nosuchdir"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd


def test_catastrophic_rm_blocked_in_any_argument_position(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("rm -rf build/ /", cwd=repo).returncode == 2
    assert run_hook("rm -rf ./build /", cwd=repo).returncode == 2
    assert run_hook("rm -rf src/a src/b ~", cwd=repo).returncode == 2


def test_literal_home_and_system_paths_are_catastrophic(tmp_path):
    home = os.path.expanduser("~")
    repo = make_repo(tmp_path, dirty=False)
    for target in (home, "/usr", "/home", "/etc/", "/var", "//", "/usr/..", "/usr/", '"/usr"',
                   "/home/../home"):
        assert run_hook(f"rm -rf {target}", cwd=repo).returncode == 2, target
    for target in (f"{home}/project/build", "/tmp/scratch", "/usr/local/share/foo", "/var/tmp/x"):
        assert run_hook(f"rm -rf {target}", cwd=repo).returncode == 0, target


def test_rm_of_repo_or_git_dir_blocked_unconditionally(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("rm -rf .git", "rm -rf ./.git", f"rm -rf {repo}", f"rm -rf {repo}/.git",
                'rm -rf "$(git rev-parse --show-toplevel)"', "rm -rf $(git rev-parse --show-toplevel)",
                "rm -rf $(git rev-parse --git-dir)"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    sub = tmp_path / "elsewhere"
    sub.mkdir()
    assert run_hook(f"rm -rf {repo}", cwd=sub).returncode == 2   # absolute path from outside


def test_rm_of_dir_holding_uncommitted_work_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    src = repo / "src"
    src.mkdir()
    (src / "a.py").write_text("committed")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "src")
    assert run_hook("rm -rf src/", cwd=repo).returncode == 0      # clean dir: routine delete
    (src / "a.py").write_text("MODIFIED")
    (src / "new_feature.py").write_text("untracked")
    r = run_hook("rm -rf src/", cwd=repo)
    assert r.returncode == 2 and "uncommitted work" in r.stderr
    assert run_hook("rm -rf src", cwd=repo).returncode == 2
    assert run_hook("rm -rf ./src", cwd=repo).returncode == 2
    assert run_hook(f"rm -rf {src}", cwd=tmp_path).returncode == 2   # absolute, from outside
    # ignored dirs never count as work
    (repo / "build").mkdir()
    (repo / "build" / "out.o").write_text("x")
    assert run_hook("rm -rf build/", cwd=repo).returncode == 0
    # a non-recursive rm of a single modified file is not this tier's concern
    assert run_hook("rm src/a.py", cwd=repo).returncode == 0


def test_rm_target_assembled_through_a_variable(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("T=/ && rm -rf $T", cwd=repo).returncode == 2
    assert run_hook('T="/usr"; rm -rf "$T"', cwd=repo).returncode == 2
    assert run_hook("D=build && rm -rf $D", cwd=repo).returncode == 0
    assert run_hook("rm -rf $UNKNOWN_DIR", cwd=repo).returncode == 0   # unresolvable: fail open


def test_quoted_path_with_glob_is_one_target(tmp_path):
    # rm -rf "$DIR"/* must not be split into `$DIR` and a catastrophic `/*` token.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook('rm -rf "$BUILD_DIR"/*', cwd=repo).returncode == 0
    assert run_hook('rm -rf "$BUILD_DIR"/', cwd=repo).returncode == 0
    assert run_hook('BUILD_DIR=/ ; rm -rf "$BUILD_DIR"/*', cwd=repo).returncode == 2


def test_git_rm_cached_is_not_a_shell_rm(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git rm -r --cached .", cwd=repo).returncode == 0
    assert run_hook("git rm -r --cached src/", cwd=repo).returncode == 0


def test_find_delete_at_catastrophic_root_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("find / -name node_modules -exec rm -rf {} +", "find ~ -delete",
                "find / -type f -delete", r"find $HOME -name '*.log' -exec rm -r {} \;"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    for cmd in ("find . -name '*.pyc' -delete", "find build -type f -delete",
                "find . -name '*.orig' -exec rm -f {} +", "find / -name foo -print"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd


def test_quoted_rm_target_still_blocked():
    assert run_hook('rm -rf "."').returncode == 2
    assert run_hook("rm -rf '/'").returncode == 2
    assert run_hook('rm -rf "${HOME}"').returncode == 2
    assert run_hook("rm -rf ${HOME}").returncode == 2


def test_rm_end_of_options_marker_still_blocked(tmp_path):
    assert run_hook("rm -rf -- /").returncode == 2


# ---- shell awareness ---------------------------------------------------------------

def test_mentions_inside_quotes_and_comments_do_not_trip(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('git commit -m "guard git reset --hard in hook"', cwd=repo).returncode == 0
    assert run_hook('echo "never run git stash clear blindly" >> notes.md', cwd=repo).returncode == 0
    assert run_hook('git commit -m "note: never run rm -rf / here"', cwd=repo).returncode == 0
    assert run_hook("ls -la  # never git reset --hard here", cwd=repo).returncode == 0
    assert run_hook("ls  # rm -rf / would be bad", cwd=repo).returncode == 0
    assert run_hook("echo '#' ; rm -rf /", cwd=repo).returncode == 2   # a quoted # is not a comment


def test_override_token_allows(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0
    assert run_hook("cd repo; HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0


def test_override_only_as_assignment_not_mere_mention(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('git commit -m "set HARDMODE_DESTRUCTIVE_OK=1 to bypass" && git reset --hard',
                    cwd=repo).returncode == 2


def test_override_is_scoped_to_its_own_segment(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard; rm -rf /", cwd=repo).returncode == 2
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard && git clean -fd", cwd=repo).returncode == 2
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard\nrm -rf /", cwd=repo).returncode == 2
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0


def test_command_substitution_in_double_quotes_is_inspected(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('echo "$(git reset --hard)"', cwd=repo).returncode == 2
    assert run_hook("echo `git clean -fd`", cwd=repo).returncode == 2
    assert run_hook("echo $(true; rm -rf /)", cwd=repo).returncode == 2


def test_single_quoted_substitution_is_literal_not_executed(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("echo '$(git reset --hard)'", cwd=repo).returncode == 0


def test_wrappers_are_scanned_through_launchers(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    for cmd in ('bash -c "git reset --hard"', "bash -c 'git reset --hard'", 'eval "git reset --hard"',
                "sh -lc 'git clean -fd'", 'sudo bash -c "rm -rf /"', 'sudo sh -c "git clean -fdx"',
                '/bin/bash -c "git reset --hard"', '/usr/bin/env bash -c "rm -rf /"',
                'timeout 30 bash -c "git reset --hard"', 'nohup bash -c "rm -rf /"',
                'FOO=1 sudo -E bash -c "rm -rf ~"'):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("echo \"bash -c 'git reset --hard'\"", cwd=repo).returncode == 0


def test_quoted_heredoc_body_is_data_unless_it_feeds_a_shell(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    quoted = "cat > notes.md <<'EOF'\nnever run rm -rf / or git reset --hard\nEOF"
    assert run_hook(quoted, cwd=repo).returncode == 0
    unquoted = 'cat > x <<EOF\n"$(rm -rf /)"\nEOF'
    assert run_hook(unquoted, cwd=repo).returncode == 2
    after = "cat > n.md <<'EOF'\nharmless\nEOF\nrm -rf /"
    assert run_hook(after, cwd=repo).returncode == 2
    # a heredoc that IS the script a shell runs is executed line by line
    for shell in ("bash <<'EOF'\ngit reset --hard\nEOF", "sh -s <<'EOF'\nrm -rf /\nEOF",
                  "cat <<'EOF' | bash\ngit clean -fd\nEOF", "sudo bash <<'EOF'\nrm -rf ~\nEOF"):
        assert run_hook(shell, cwd=repo).returncode == 2, shell
    # a MENTION of <<'EOF' inside a string must not blank the rest of the command
    mention = "echo \"docs use <<'EOF' style\" ; rm -rf /"
    assert run_hook(mention, cwd=repo).returncode == 2


def test_cd_into_dirty_repo_from_clean_cwd_blocks(tmp_path):
    dirty = make_repo(tmp_path, dirty=True, name="dirty")
    clean = make_repo(tmp_path, dirty=False, name="clean")
    assert run_hook(f"cd {dirty} && git reset --hard", cwd=clean).returncode == 2
    assert run_hook(f"cd {clean} && git reset --hard", cwd=clean).returncode == 0
    assert run_hook(f"git -C {dirty} reset --hard", cwd=clean).returncode == 2
    assert run_hook(f"pushd {dirty}; git reset --hard", cwd=clean).returncode == 2
    assert run_hook(f"git --work-tree {dirty} --git-dir {dirty}/.git reset --hard",
                    cwd=clean).returncode == 2


def test_quoted_directory_with_spaces_is_resolved(tmp_path):
    dirty = make_repo(tmp_path, dirty=True, name="my repo")
    clean = make_repo(tmp_path, dirty=False, name="clean")
    assert run_hook(f'cd "{dirty}" && git reset --hard', cwd=clean).returncode == 2
    assert run_hook(f"git -C '{dirty}' reset --hard", cwd=clean).returncode == 2


# ---- fail-open and misc --------------------------------------------------------------

def test_non_git_cwd_fails_open(tmp_path):
    assert run_hook("git reset --hard", cwd=tmp_path).returncode == 0


def test_non_bash_tool_ignored():
    assert run_hook("git reset --hard", tool_name="Edit").returncode == 0
    assert run_hook("git reset --hard", tool_name="PowerShell").returncode == 0


def test_malformed_stdin_fails_open():
    assert run_hook("", raw_stdin="not json").returncode == 0


def test_non_ascii_command_does_not_crash_the_guard(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    payload = {"tool_name": "Bash", "tool_input": {"command": "rm -rf / # \U0001f355 löschen"},
               "cwd": str(repo)}
    env = dict(os.environ, PYTHONIOENCODING="cp1252", HARDMODE_STATE_DIR=str(tmp_path / "st"))
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=30, env=env)
    assert r.returncode == 2


def test_block_and_override_are_written_to_the_ledger(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    state = tmp_path / "state"
    assert run_hook("git reset --hard", cwd=repo, state_dir=state).returncode == 2
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo, state_dir=state).returncode == 0
    ledger = state / "ledger-guard-test.jsonl"
    recs = [json.loads(ln) for ln in ledger.read_text(encoding="utf-8").splitlines()]
    outcomes = [(r["hook"], r["outcome"], r["detail"]) for r in recs]
    assert ("destructive-guard", "block", "reset-hard") in outcomes
    assert any(o == "override" for _, o, _ in outcomes)


def test_ledger_can_be_disabled(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    state = tmp_path / "state"
    env = dict(os.environ, HARDMODE_STATE_DIR=str(state), HARDMODE_LEDGER="0")
    payload = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"},
               "cwd": str(repo), "session_id": "s"}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 2
    assert not (state / "ledger-s.jsonl").exists()


# ---- review-round regressions ---------------------------------------------------------

def test_quoted_branch_names_are_read_and_substituted_ones_block(tmp_path):
    # The merged-check runs `git branch --no-merged` and compares NAMES: a quoted name is
    # still a name; a command substitution or variable cannot be compared, so it blocks.
    repo = make_repo(tmp_path, dirty=False)
    git(repo, "branch", "merged")
    git(repo, "checkout", "-q", "-b", "wip")
    (repo / "wip.txt").write_text("w")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "wip")
    git(repo, "checkout", "-q", "main")
    for cmd in ("git branch -D merged", 'git branch -D "merged"', "git branch -D 'merged'", "git branch --delete --force merged"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd
    for cmd in ("git branch -D wip", 'git branch -D "wip"', "git branch -D merged wip", "git branch -D $(git branch --show-current)",
                "git branch -D `cat name`", "git branch -D ${BR}", "git branch -D $BR"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("git branch -d wip", cwd=repo).returncode == 0          # -d refuses unmerged by itself


def test_quoted_paths_are_scoped_like_bare_ones(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('git checkout -- "tracked.txt"', cwd=repo).returncode == 0     # unmodified
    (repo / "tracked.txt").write_text("changed\n")
    assert run_hook('git checkout -- "tracked.txt"', cwd=repo).returncode == 2
    assert run_hook("git checkout -- 'tracked.txt'", cwd=repo).returncode == 2
    assert run_hook('git restore "tracked.txt"', cwd=repo).returncode == 2


def test_home_and_pwd_expansion_cannot_hide_the_repo(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    env = {"HOME": str(tmp_path)}
    for cmd in ("rm -rf $HOME/repo", "rm -rf ${HOME}/repo", "rm -rf ~/repo", "rm -rf $PWD",
                "rm -rf $(pwd)", "rm -rf $(git rev-parse --show-toplevel)", "R=$HOME/repo; rm -rf $R"):
        assert run_hook(cmd, cwd=repo, env_extra=env).returncode == 2, cmd
    assert run_hook("rm -rf $HOME/elsewhere", cwd=repo, env_extra=env).returncode == 0


def test_find_piped_into_xargs_rm_is_judged_by_its_start_dirs(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("find / -name '*.tmp' | xargs rm -rf", "find ~ -type f | xargs -0 rm -f", "find $HOME -name x | xargs rm -r",
                "find /usr /etc -name x | xargs rm -rf", "find / -name x -print0 | xargs -0 rm -rf"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    (repo / "build").mkdir()
    # a targeted find inside the tree is the everyday idiom (a piped rm cannot be judged
    # for uncommitted work — that needs literal paths — so only catastrophic roots block)
    for cmd in ("find ./build -name '*.o' | xargs rm -f", "find . -name '*.pyc' -delete", f"find {repo} -name x | xargs rm -rf",
                "find build -type f -exec rm -f {} \\;", "git ls-files | xargs rm -f", "echo build | xargs rm -rf"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd


def test_force_if_includes_is_the_safe_push(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("git push --force-with-lease --force-if-includes origin main",
                "git push --force-with-lease=main:abc123 --force-if-includes origin main",
                "git push --force --dry-run origin main"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd
    for cmd in ("git push --force origin main", "git push -f origin main", "git push --force-if-includes --force origin main",
                "git push origin +main", "git push -uf origin main"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd


def test_unquoted_heredoc_prose_is_not_a_command(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("cat <<EOF\nNever run rm -rf / or git reset --hard here.\nEOF", cwd=repo).returncode == 0
    assert run_hook("cat <<'EOF'\nrm -rf /\nEOF", cwd=repo).returncode == 0
    assert run_hook("cat > notes.md <<EOF\n# git push --force is banned\nEOF", cwd=repo).returncode == 0
    # ...but an unquoted body still EXECUTES substitutions, and a heredoc fed to a shell runs
    assert run_hook("cat <<EOF\n$(rm -rf /)\nEOF", cwd=repo).returncode == 2
    assert run_hook("bash <<EOF\nrm -rf /\nEOF", cwd=repo).returncode == 2
    assert run_hook("sh <<'EOF'\ngit reset --hard\nEOF", cwd=repo).returncode == 2


def test_multi_line_commands_are_matched_after_a_newline(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    for cmd in ("echo start\ngit push --force origin main", "set -e\nrm -rf /", "cd src\ngit reset --hard",
                "git status \\\n  && git checkout -- .", "true\n\ngit stash drop"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("echo one\necho 'rm -rf /'\ngit status", cwd=repo).returncode == 0


def test_missing_cwd_falls_back_to_the_process_directory(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git reset --hard", cwd=None, proc_cwd=repo).returncode == 2
    assert run_hook("git reset --hard", cwd=None, proc_cwd=make_repo(tmp_path, dirty=False, name="clean")).returncode == 0


def test_symlinked_repo_path_is_recognised(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    assert run_hook(f"rm -rf {link}", cwd=repo).returncode == 2
    assert run_hook(f"rm -rf {link}/.git", cwd=repo).returncode == 2
    assert run_hook("rm -rf ../link", cwd=repo).returncode == 2


def test_always_dangerous_git_plumbing(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("git stash drop", "git stash clear", "git reflog expire --expire=now --all", "git gc --prune=now",
                "git update-ref -d refs/heads/main", "git worktree remove --force ../wt", "git push origin --delete main",
                "git push origin :main", "shred -u secrets.txt"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    for cmd in ("git stash", "git stash list", "git reflog", "git gc", "git worktree remove ../wt",
                "git push origin --delete main --dry-run", "git push origin main"):
        assert run_hook(cmd, cwd=repo).returncode == 0, cmd
