# Docs-integrity guards. A succession kit whose documentation rots is a kit
# that misleads its heirs — these keep the load-bearing references honest.
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "CHANGELOG.md",
        *sorted((ROOT / "docs").glob("*.md")), ROOT / "bench" / "README.md"]

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def test_relative_markdown_links_resolve():
    broken = []
    for doc in DOCS:
        # utf-8 explicitly: the docs contain non-ASCII (em-dashes, the demo's emoji);
        # the OS-locale default (cp1252 on Windows) would crash the read — the same
        # encoding bug this kit hardens its hooks against.
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = target.split("#")[0]
            if path and not (doc.parent / path).exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, f"broken relative links: {broken}"


def test_succession_knobs_are_real():
    # Every config knob SUCCESSION.md tells an heir to set must exist in the code
    # it claims to configure.
    succession = (ROOT / "docs" / "SUCCESSION.md").read_text(encoding="utf-8")
    loop_alarm = (ROOT / "claude" / "hooks" / "posttool-loop-alarm.py").read_text(encoding="utf-8")
    assert "FABLE_LOOP_THRESHOLD" in succession
    assert "FABLE_LOOP_THRESHOLD" in loop_alarm
    # ...and the workflows it routes small models to are the ones that ship.
    for wf in ("paranoid-review", "verify-claim", "deep-plan", "bug-hunt"):
        assert wf in succession
        assert (ROOT / "claude" / "workflows" / f"{wf}.js").is_file()


def test_oracle_carries_the_field_notes():
    # The diagnostic priors must live where they are read at the moment of need,
    # not only in the docs.
    oracle = (ROOT / "claude" / "agents" / "oracle.md").read_text(encoding="utf-8")
    assert "Field notes" in oracle
    assert "reproducer" in oracle.lower()


def test_state_env_var_consistent_across_stateful_hooks():
    # All stateful hooks must honor the same override, or SUCCESSION.md's
    # environment advice silently applies to only some of them.
    hooks = ROOT / "claude" / "hooks"
    for name in ("posttool-loop-alarm.py", "posttool-test-weakening-alarm.py",
                 "precompact-save-task.py", "sessionstart-compact-recovery.py",
                 "userpromptsubmit-mem-recall.py"):
        assert "FABLE_STATE_DIR" in (hooks / name).read_text(encoding="utf-8"), name
