# Docs-integrity guards. A kit whose documentation rots misleads whoever installs it —
# these keep every load-bearing reference honest against the code.
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted(set([ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "doctrine" / "CLAUDE.md",
                   *(ROOT / "docs").glob("*.md"), *(ROOT / "bench").glob("*.md"),
                   *(ROOT / "skills").glob("*/SKILL.md"), *(ROOT / "agents").glob("*.md"),
                   *(ROOT / "commands").glob("*.md")]))
SOURCES = sorted([*(ROOT / "hooks").glob("*.py"), *(ROOT / "tools").glob("*.py"), *(ROOT / "tools").glob("*.mjs")])
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# A bare repo-relative path in prose or a docstring: docs/x.md, hooks/x.py, tools/x, bench/x
# (tests/ is excluded: docs and docstrings use illustrative test paths such as tests/test_x.py)
BARE_PATH = re.compile(r"(?<![\w/.-])((?:docs|hooks|tools|bench|skills|agents|commands|doctrine|workflows)/[A-Za-z0-9_./-]+\.(?:md|py|mjs|json|js|toml|sh))\b")


def read(p):
    return p.read_text(encoding="utf-8")


def test_relative_markdown_links_resolve():
    broken = []
    for doc in DOCS:
        for target in LINK.findall(read(doc)):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = target.split("#")[0]
            if path and not (doc.parent / path).exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, f"broken relative links: {broken}"


def test_bare_repo_paths_in_docs_and_sources_resolve():
    # `docs/SUCCESSION.md` in a docstring and `claude/hooks/...` in a comment both rotted
    # unnoticed because only markdown links were checked.
    dangling = []
    for f in DOCS + SOURCES:
        if f.name in ("CHANGELOG.md", "RESULTS.md"):
            continue  # history names what was removed
        for m in BARE_PATH.findall(read(f)):
            if m.endswith(("*.py", "*.md")):
                continue
            if not (ROOT / m).exists():
                dangling.append(f"{f.relative_to(ROOT)}: {m}")
    assert not dangling, f"dangling repo paths: {dangling}"


def test_no_references_to_deleted_or_never_shipped_components():
    # operator-private tools that the public plugin does not ship, and v3.0 deletions
    banned = ("memdb", "ultraweb", "mem.py", "SUCCESSION", "install.sh", "doctor.sh", "run.sh",
              "PROMPT.txt", "weakening-alarm", "PowerShell", "CLAUDE_DIR ")
    hits = []
    for f in DOCS + SOURCES:
        if f.name in ("CHANGELOG.md", "RESULTS.md"):
            continue  # history is allowed to name what was removed
        text = read(f)
        for b in banned:
            if b in text:
                hits.append(f"{f.relative_to(ROOT)}: {b}")
    assert not hits, hits


def test_documented_workflows_and_commands_ship_and_are_namespaced():
    readme = read(ROOT / "README.md")
    for wf in ("paranoid-review", "verify-claim", "deep-plan", "bug-hunt", "increment"):
        assert f"/hardmode:{wf}" in readme, wf
        assert (ROOT / "workflows" / f"{wf}.js").is_file(), wf
    for cmd in ("doctor", "stats", "selftest"):
        assert f"/hardmode:{cmd}" in readme and (ROOT / "commands" / f"{cmd}.md").is_file(), cmd
    # a bare slash command for a plugin workflow does not exist — no doc may teach it
    for doc in DOCS:
        if doc.name in ("CHANGELOG.md", "RESULTS.md"):
            continue
        for wf in ("paranoid-review", "verify-claim", "deep-plan", "bug-hunt", "increment"):
            assert not re.search(rf"(?<!hardmode:)/{wf}\b", read(doc)), f"{doc.name} teaches the bare /{wf}"
    for wf in (ROOT / "workflows").glob("*.js"):
        src = read(wf)
        name = re.search(r"name:\s*'([^']+)'", src).group(1)
        assert f"/hardmode:{name}" in src, f"{wf.name} whenToUse must name /hardmode:{name}"


def test_readme_inventory_matches_the_tree():
    readme = read(ROOT / "README.md")
    wiring = json.loads(read(ROOT / "hooks" / "hooks.json"))
    hooks = {h["command"].rstrip('"').split("/")[-1] for gs in wiring["hooks"].values() for g in gs for h in g["hooks"]}
    assert f"**{len(hooks)} hooks**" in readme
    assert f"**{len(list((ROOT / 'agents').glob('*.md')))} agents**" in readme
    assert f"**{len(list((ROOT / 'workflows').glob('*.js')))} workflows**" in readme
    assert f"**{len(list((ROOT / 'commands').glob('*.md')))} commands**" in readme
    assert f"**{len(list((ROOT / 'skills').glob('*/SKILL.md')))} skills**" in readme
    for h in hooks:
        assert h[:-3] in readme, f"README does not mention hook {h}"


def test_readme_and_design_claim_the_demo_count_the_demo_actually_has():
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo", ROOT / "tools" / "demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    n = len(demo.SCENARIOS)
    assert f"demo: {n}/{n} scenarios behed as expected".replace("behed", "behaved") in read(ROOT / "README.md")
    assert re.search(r"\d+/\d+ proves", read(ROOT / "README.md") + read(ROOT / "docs" / "DESIGN.md")) is None


def test_plugin_manifest_is_minimal_and_versioned():
    m = json.loads(read(ROOT / ".claude-plugin" / "plugin.json"))
    assert m["name"] == "hardmode" and re.fullmatch(r"\d+\.\d+\.\d+", m["version"])
    # keys older harnesses reject; workflows/ and commands/ are discovered by convention
    assert "displayName" not in m and "workflows" not in m and "commands" not in m
    major_minor = ".".join(m["version"].split(".")[:2])
    assert f"## v{major_minor}" in read(ROOT / "CHANGELOG.md")
    mk = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    assert mk["metadata"]["description"]


def test_loop_threshold_knob_is_real():
    assert "HARDMODE_LOOP_THRESHOLD" in read(ROOT / "hooks" / "posttool-loop-alarm.py")


def test_all_agents_pin_a_model_and_are_read_only_enforced():
    agents = list((ROOT / "agents").glob("*.md"))
    assert agents
    ro = read(ROOT / "hooks" / "pretool-readonly-agent.py")
    for agent in agents:
        fm = read(agent).split("---")[1]
        assert "\nmodel:" in fm, f"{agent.name} ships without a model pin"
        assert f'"{agent.stem}"' in ro, f"{agent.name} is not in the read-only agent set"


def test_oracle_carries_the_field_notes():
    oracle = read(ROOT / "agents" / "oracle.md")
    assert "Field notes" in oracle and "reproducer" in oracle.lower()


def test_state_and_config_dirs_come_from_the_shared_module():
    # Every stateful hook must derive its dirs from _hardmode (HARDMODE_STATE_DIR and
    # CLAUDE_CONFIG_DIR honoured in one place), never hand-roll ~/.claude.
    shared = read(ROOT / "hooks" / "_hardmode.py")
    assert "HARDMODE_STATE_DIR" in shared and "CLAUDE_CONFIG_DIR" in shared
    for hook in (ROOT / "hooks").glob("*.py"):
        if hook.name.startswith("_"):
            continue
        text = read(hook)
        assert "from _hardmode import" in text, hook.name
        assert 'expanduser("~/.claude")' not in text and "expanduser('~/.claude')" not in text, \
            f"{hook.name} hand-rolls the config dir"


def test_settings_snippet_matches_the_doctor_expectations():
    ref = json.loads(read(ROOT / "doctrine" / "settings-snippet.json"))
    assert ref["effortLevel"] == "xhigh" and ref["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]
