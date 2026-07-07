# The webdesign skill: files, frontmatter, load-bearing content, and the
# multi-file-skill install path it forced into install.sh / doctor.sh.
# A skill whose reference docs silently fail to install is worse than no skill:
# the model would follow the protocol but gate against a checklist that isn't there.
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "claude" / "skills" / "webdesign"
INSTALL = ROOT / "install.sh"
DOCTOR = ROOT / "tools" / "doctor.sh"


def run(script, claude_dir, state_dir=None):
    env = dict(os.environ, CLAUDE_DIR=str(claude_dir))
    if state_dir:
        env["FABLE_STATE_DIR"] = str(state_dir)
    return subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          timeout=60, env=env)


def install_and_merge_settings(claude_dir):
    r = run(INSTALL, claude_dir)
    assert r.returncode == 0, r.stderr
    snippet = json.loads((ROOT / "claude" / "settings" / "settings-snippet.json").read_text())
    (claude_dir / "settings.json").write_text(json.dumps(snippet))


def test_skill_files_exist():
    assert (SKILL / "SKILL.md").is_file()
    assert (SKILL / "references" / "design-views.md").is_file()
    assert (SKILL / "references" / "german-market.md").is_file()


def test_frontmatter_names_the_triggers():
    text = (SKILL / "SKILL.md").read_text()
    m = re.match(r"---\nname: webdesign\ndescription: (?P<desc>.+?)\n---\n", text)
    assert m, "SKILL.md must open with name/description frontmatter"
    desc = m.group("desc").lower()
    # The description is the trigger surface: it must fire on website work,
    # on the German market, and on the design-view vocabulary.
    for token in ("website", "german", "static", "animated"):
        assert token in desc, f"skill description must mention '{token}' to trigger"


def test_skill_points_at_its_references():
    text = (SKILL / "SKILL.md").read_text()
    for ref in ("references/design-views.md", "references/german-market.md"):
        assert ref in text, f"SKILL.md must route the model to {ref}"
        assert (SKILL / ref).is_file()


def test_german_market_carries_the_laws():
    # The compliance gate is only as good as the laws it names. These are the
    # load-bearing ones as of mid-2026 (verified against live sources in v1.7).
    text = (SKILL / "references" / "german-market.md").read_text()
    for token in ("DDG", "DSGVO", "TDDDG", "BFSG", "Impressum",
                  "Datenschutzerklärung", "prefers-reduced-motion"):
        assert token in text, f"german-market.md must carry '{token}'"


def test_design_views_cover_the_taxonomy():
    text = (SKILL / "references" / "design-views.md").read_text().lower()
    for view in ("static", "animated", "interactive", "immersive", "commerce"):
        assert view in text, f"design-views.md must cover the '{view}' view"
    for invariant in ("prefers-reduced-motion", "lcp", "inp", "cls"):
        assert invariant in text, f"design-views.md must carry '{invariant}'"


def test_design_variants_workflow_ships():
    wf = (ROOT / "claude" / "workflows" / "design-variants.js").read_text()
    assert wf.startswith("export const meta = {")
    assert "name: 'design-variants'" in wf
    # The judges are the verification layer — they must hold xhigh (kit rule:
    # asymmetric verification survives a low-effort session).
    assert "effort: 'xhigh'" in wf


def test_doctrine_routes_design_work_to_the_skill():
    doctrine = (ROOT / "claude" / "CLAUDE.md").read_text()
    assert "webdesign" in doctrine, "doctrine must route website work to the skill"


def test_install_copies_the_full_skill_dir(tmp_path):
    # Regression for the v1.7 installer change: skills used to install as bare
    # SKILL.md — references/ would silently not arrive.
    claude = tmp_path / "claude"
    r = run(INSTALL, claude)
    assert r.returncode == 0, r.stderr
    for rel in ("SKILL.md", "references/design-views.md", "references/german-market.md"):
        src, dst = SKILL / rel, claude / "skills" / "webdesign" / rel
        assert dst.is_file(), f"{rel} did not install"
        assert dst.read_text() == src.read_text(), f"{rel} installed with drift"
    # Idempotency must survive the multi-file check: second run backs up nothing.
    r2 = run(INSTALL, claude)
    assert r2.returncode == 0
    assert "webdesign (unchanged)" in r2.stdout
    assert not (claude / "fable-protocol-backups").exists(), "idempotent re-run must not churn backups"


def test_install_preserves_user_extra_files_in_skill_dir(tmp_path):
    # A user's own notes inside an installed skill dir must survive re-install
    # and must not break idempotency detection for shipped files.
    claude = tmp_path / "claude"
    r = run(INSTALL, claude)
    assert r.returncode == 0
    extra = claude / "skills" / "webdesign" / "references" / "my-notes.md"
    extra.write_text("mine\n")
    r2 = run(INSTALL, claude)
    assert r2.returncode == 0
    assert "webdesign (unchanged)" in r2.stdout
    assert extra.read_text() == "mine\n"


def test_install_prunes_formerly_shipped_skill_files(tmp_path):
    # A file an OLDER kit version shipped (tracked in .fable-manifest) but the
    # current version doesn't must be pruned on upgrade — a stale legal checklist
    # sitting beside the current one is silent drift. User files (never in a
    # manifest) must survive the same upgrade.
    claude = tmp_path / "claude"
    r = run(INSTALL, claude)
    assert r.returncode == 0
    sk = claude / "skills" / "webdesign"
    stale = sk / "references" / "old-checklist.md"
    stale.write_text("outdated legal advice\n")
    manifest = sk / ".fable-manifest"
    manifest.write_text(manifest.read_text() + "./references/old-checklist.md\n")
    mine = sk / "references" / "my-notes.md"
    mine.write_text("mine\n")
    r2 = run(INSTALL, claude)
    assert r2.returncode == 0
    assert not stale.exists(), "manifest-tracked stale file must be pruned on upgrade"
    assert mine.read_text() == "mine\n", "user file must survive the upgrade"
    # and the manifest is regenerated to the current ship-list
    assert "old-checklist" not in manifest.read_text()


def test_doctor_fails_on_missing_skill_reference(tmp_path):
    # Regression for the v1.7 doctor change: a skill missing its reference docs
    # used to pass (only SKILL.md was checked).
    claude = tmp_path / "claude"
    install_and_merge_settings(claude)
    (claude / "skills" / "webdesign" / "references" / "german-market.md").unlink()
    r = run(DOCTOR, claude, state_dir=tmp_path / "state")
    assert r.returncode == 1
    assert "skill file missing" in r.stdout and "german-market.md" in r.stdout
