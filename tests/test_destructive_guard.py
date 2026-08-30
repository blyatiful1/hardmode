# Unit tests for the PreToolUse destructive-command guard.
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "pretool-destructive-guard.py"


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
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0
    # Also valid as a segment-leading assignment after a separator.
    assert run_hook("cd repo; HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0


def test_override_only_as_assignment_not_mere_mention(tmp_path):
    # CONF5: the override string inside a quoted commit message (or any non-assignment
    # position) must NOT disable the guard for the rest of the command.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook(
        'git commit -m "set HARDMODE_DESTRUCTIVE_OK=1 to bypass" && git reset --hard',
        cwd=repo).returncode == 2


def test_override_is_scoped_to_its_own_segment(tmp_path):
    # The override is a shell env-assignment prefix — it approves only the command it
    # prefixes. A later, UNAPPROVED destructive segment must still be blocked.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook(
        "HARDMODE_DESTRUCTIVE_OK=1 git reset --hard; rm -rf /", cwd=repo).returncode == 2
    assert run_hook(
        "HARDMODE_DESTRUCTIVE_OK=1 git reset --hard && git clean -fd", cwd=repo).returncode == 2
    # A bare NEWLINE is a command separator too — the override must not leak across it.
    assert run_hook(
        "HARDMODE_DESTRUCTIVE_OK=1 git reset --hard\nrm -rf /", cwd=repo).returncode == 2
    # ...but the approved segment alone still passes.
    assert run_hook("HARDMODE_DESTRUCTIVE_OK=1 git reset --hard", cwd=repo).returncode == 0


def test_command_substitution_in_double_quotes_is_inspected(tmp_path):
    # A destructive command hidden in "$(...)" or `...` still executes — the guard must
    # see through the surrounding double quotes.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('echo "$(git reset --hard)"', cwd=repo).returncode == 2
    assert run_hook("echo `git clean -fd`", cwd=repo).returncode == 2
    # A separator INSIDE the substitution must not split it away from the scan.
    assert run_hook("echo $(true; rm -rf /)", cwd=repo).returncode == 2


def test_single_quoted_substitution_is_literal_not_executed(tmp_path):
    # Single quotes suppress command substitution, so '$(...)' is a literal string and
    # must NOT be treated as a hidden command (no false block).
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("echo '$(git reset --hard)'", cwd=repo).returncode == 0


def test_braced_home_expansion_is_a_catastrophic_rm_target(tmp_path):
    # rm -rf "${HOME}" expands to the home dir exactly like $HOME — both must block.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('rm -rf "${HOME}"', cwd=repo).returncode == 2
    assert run_hook("rm -rf ${HOME}", cwd=repo).returncode == 2


def test_rm_phrase_in_commit_message_does_not_false_trip(tmp_path):
    # A commit message that merely MENTIONS `rm -rf /` is not an rm command; only a
    # genuine (even quoted) target should block.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('git commit -m "note: never run rm -rf / here"', cwd=repo).returncode == 0
    assert run_hook('rm -rf "/"', cwd=repo).returncode == 2


def test_non_git_cwd_fails_open(tmp_path):
    assert run_hook("git reset --hard", cwd=tmp_path).returncode == 0


def test_non_bash_tool_ignored():
    assert run_hook("git reset --hard", tool_name="Edit").returncode == 0


def test_malformed_stdin_fails_open():
    assert run_hook("", raw_stdin="not json").returncode == 0


# ---- multi-target and long-form rm (the stray-space catastrophe) ----

def test_catastrophic_rm_blocked_in_any_argument_position(tmp_path):
    # `rm -rf build/ /` is the canonical accidental-space typo: the FIRST target is
    # harmless, the second is /. Every argument must be scanned, not just the first.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("rm -rf build/ /", cwd=repo).returncode == 2
    assert run_hook("rm -rf ./build /", cwd=repo).returncode == 2
    assert run_hook("rm -rf src/a src/b ~", cwd=repo).returncode == 2


def test_long_form_recursive_rm_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("rm --recursive --force /", cwd=repo).returncode == 2
    assert run_hook("rm --recursive /", cwd=repo).returncode == 2


def test_scoped_multi_target_rm_allowed(tmp_path):
    # Multiple SAFE targets must not trip the all-arguments scan.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("rm -rf build/ dist/ node_modules/", cwd=repo).returncode == 0
    assert run_hook("rm --recursive build/", cwd=repo).returncode == 0


def test_rm_end_of_options_marker_still_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("rm -rf -- /", cwd=repo).returncode == 2


def test_quoted_heredoc_body_is_data_not_commands(tmp_path):
    # A <<'EOF' heredoc body is literal data (no expansions run inside) — writing a
    # doc/test that MENTIONS destructive commands must not trip the guard. An
    # UNQUOTED delimiter is different: $(...) executes inside, so it stays guarded.
    repo = make_repo(tmp_path, dirty=True)
    quoted = "cat > notes.md <<'EOF'\nnever run rm -rf / or git reset --hard\nEOF"
    assert run_hook(quoted, cwd=repo).returncode == 0
    unquoted = 'cat > x <<EOF\n"$(rm -rf /)"\nEOF'
    assert run_hook(unquoted, cwd=repo).returncode == 2
    after = "cat > n.md <<'EOF'\nharmless\nEOF\nrm -rf /"
    assert run_hook(after, cwd=repo).returncode == 2


# ---- PowerShell tool (native-Windows sessions; Windows snippets match Bash|PowerShell) ----

def test_powershell_git_destroyers_guarded(tmp_path):
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook("git reset --hard HEAD~1", cwd=repo, tool_name="PowerShell").returncode == 2
    assert run_hook("git stash drop", cwd=repo, tool_name="PowerShell").returncode == 2
    assert run_hook("git push --force origin main", cwd=repo, tool_name="PowerShell").returncode == 2
    assert run_hook("git push --force-with-lease origin main", cwd=repo,
                    tool_name="PowerShell").returncode == 0


def test_powershell_remove_item_catastrophic_blocked(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("Remove-Item -Recurse -Force C:\\", cwd=repo,
                    tool_name="PowerShell").returncode == 2
    assert run_hook("Remove-Item -Path C:\\ -Recurse", cwd=repo,
                    tool_name="PowerShell").returncode == 2
    assert run_hook("rm -r -fo ~", cwd=repo, tool_name="PowerShell").returncode == 2
    assert run_hook("ri -Recurse $env:USERPROFILE", cwd=repo,
                    tool_name="PowerShell").returncode == 2


def test_powershell_scoped_remove_item_allowed(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("Remove-Item -Recurse -Force .\\build", cwd=repo,
                    tool_name="PowerShell").returncode == 0
    # -Filter merely CONTAINS an r; it is not a recursive flag.
    assert run_hook("Remove-Item -Filter *.tmp .\\build", cwd=repo,
                    tool_name="PowerShell").returncode == 0


def test_non_ascii_command_does_not_crash_the_guard(tmp_path):
    # Payloads are UTF-8; under a legacy-console encoding a non-ASCII command must
    # neither crash the guard (fail-open would silently disable it) nor be misread.
    # Bytes stdin + PYTHONIOENCODING simulate the worst-case Windows console.
    import os
    repo = make_repo(tmp_path, dirty=False)
    payload = {"tool_name": "Bash",
               "tool_input": {"command": "rm -rf / # \U0001f355 löschen"},
               "cwd": str(repo)}
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    # ensure_ascii=False is load-bearing: with the default (True) the emoji is escaped
    # to ASCII \uXXXX and the bytes on the wire never stress json.load's decode path,
    # so the test would pass even with the guard's UTF-8 reconfigure reverted. Sending
    # the real UTF-8 bytes is what proves the guard did not silently fail open.
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=30, env=env)
    assert r.returncode == 2


# ---- regressions caught by the diff's own adversarial review ----

def test_powershell_force_is_not_a_recursive_flag(tmp_path):
    # -Force does not recurse; `Remove-Item -Force *` clears a dir's files and must
    # pass exactly like bash `rm -f *`. The recursive detector must not read the 'r'
    # in F-o-r-c-e as a recursive short flag.
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("Remove-Item -Force *", cwd=repo, tool_name="PowerShell").returncode == 0
    assert run_hook("Remove-Item -Force .", cwd=repo, tool_name="PowerShell").returncode == 0
    assert run_hook("rm -f *", cwd=repo).returncode == 0
    # -Recurse together with -Force at a catastrophic target still blocks.
    assert run_hook("Remove-Item -Force -Recurse C:\\", cwd=repo,
                    tool_name="PowerShell").returncode == 2


def test_long_combined_short_recursive_flags_still_block(tmp_path):
    # `rm -rfvi /` / `rm -Rfiv /` are recursive deletes of root with 3+ letters after
    # r — a bounded {0,2} matcher regressed these to ALLOW. Every combined short flag
    # containing r/R must count.
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("rm -rfvi /", "rm -Rfiv /", "rm -rfvd /", "rm -fvir /"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd


def test_powershell_recurse_switch_syntax_blocks(tmp_path):
    repo = make_repo(tmp_path, dirty=False)
    assert run_hook("Remove-Item -Recurse:$true C:\\", cwd=repo,
                    tool_name="PowerShell").returncode == 2
    assert run_hook("Remove-Item -rec C:\\", cwd=repo, tool_name="PowerShell").returncode == 2


def test_cd_into_dirty_repo_from_clean_cwd_blocks(tmp_path):
    # The destroyer runs in the directory the command cd's into, not the harness cwd.
    # `cd <dirty> && git reset --hard` from a clean/non-repo cwd must still block.
    dirty = make_repo(tmp_path, dirty=True)
    cdir = tmp_path / "c"; cdir.mkdir()
    clean = make_repo(cdir, dirty=False)
    assert run_hook(f"cd {dirty} && git reset --hard", cwd=clean).returncode == 2
    # cd into a genuinely clean repo still passes.
    assert run_hook(f"cd {clean} && git reset --hard", cwd=clean).returncode == 0


def test_git_dash_C_into_dirty_repo_blocks(tmp_path):
    dirty = make_repo(tmp_path, dirty=True)
    cdir = tmp_path / "c"; cdir.mkdir()
    clean = make_repo(cdir, dirty=False)
    assert run_hook(f"git -C {dirty} reset --hard", cwd=clean).returncode == 2


def test_bash_c_and_eval_wrappers_are_scanned(tmp_path):
    # A tree-destroyer wrapped in `bash -c "…"` / `eval "…"` still executes; the guard
    # must see through the wrapper on a dirty tree.
    repo = make_repo(tmp_path, dirty=True)
    assert run_hook('bash -c "git reset --hard"', cwd=repo).returncode == 2
    assert run_hook("bash -c 'git reset --hard'", cwd=repo).returncode == 2
    assert run_hook('eval "git reset --hard"', cwd=repo).returncode == 2
    assert run_hook("sh -lc 'git clean -fd'", cwd=repo).returncode == 2
    # A mere echo of a bash -c string is a mention, not a wrapper at command position.
    assert run_hook("echo \"bash -c 'git reset --hard'\"", cwd=repo).returncode == 0


def test_literal_home_and_system_paths_are_catastrophic(tmp_path):
    # A model that expands the path itself (`rm -rf /home/<user>`, `rm -rf /usr`) was
    # previously unguarded; the literal whole-system / whole-home target must block.
    import os
    home = os.path.expanduser("~")
    repo = make_repo(tmp_path, dirty=False)
    for target in (home, "/usr", "/home", "/etc/", "/var"):
        assert run_hook(f"rm -rf {target}", cwd=repo).returncode == 2, target
    # ...but a NESTED path under home or a system dir is a scoped delete and passes.
    for target in (f"{home}/project/build", "/tmp/scratch", "/usr/local/share/foo"):
        assert run_hook(f"rm -rf {target}", cwd=repo).returncode == 0, target


def test_catastrophic_glob_of_home_and_roots_blocks(tmp_path):
    # `rm -rf ~/*` / `$HOME/*` / `./*` wipe the same tree as the bare target; the glob
    # form of every catastrophic target must block, not only `/*`.
    repo = make_repo(tmp_path, dirty=False)
    for cmd in ("rm -rf ~/*", "rm -rf $HOME/*", "rm -rf ${HOME}/*", "rm -rf ./*", "rm -rf ../*"):
        assert run_hook(cmd, cwd=repo).returncode == 2, cmd
    assert run_hook("Remove-Item -Recurse C:\\*", cwd=repo, tool_name="PowerShell").returncode == 2
    assert run_hook("Remove-Item -Recurse $env:USERPROFILE\\*", cwd=repo,
                    tool_name="PowerShell").returncode == 2
    # A glob of a NON-catastrophic dir stays allowed.
    assert run_hook("rm -rf ~/projects/*", cwd=repo).returncode == 0
    assert run_hook("rm -rf build/*", cwd=repo).returncode == 0
