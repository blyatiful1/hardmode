# Behavioural tests for the shipped workflow scripts: each runs under tests/workflow_harness.mjs
# with stubbed agent()/parallel()/pipeline() so the control flow (halting, honesty fields,
# dedup, dead-finder bookkeeping) is exercised without spawning agents.
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "workflow_harness.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


def run(tmp_path, name, spec):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    r = subprocess.run([NODE, str(HARNESS), str(ROOT / "workflows" / f"{name}.js"), str(p)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def slice_(n):
    return {"title": f"s{n}", "files": [f"f{n}.py"], "check": f"check{n}", "doneWhen": f"done{n}"}


BUILT = {"summary": "did it", "changed": ["f.py"], "checkOutput": "ok", "checkPassed": True}
PASS = {"verdict": "pass", "evidence": "ran the check: passed"}
FAIL = {"verdict": "fail", "evidence": "the check failed"}


# ---- increment ----

def test_increment_halts_on_the_first_slice_that_does_not_verify(tmp_path):
    out = run(tmp_path, "increment", {"args": "add a --top flag", "agents": {
        "slice": {"slices": [slice_(1), slice_(2), slice_(3)], "endCheck": "make check"},
        "build:1": BUILT, "verify:1": PASS,
        "build:2": BUILT, "verify:2": [FAIL, FAIL], "repair:2": BUILT,
    }})
    res = out["result"]
    assert res["completed"] == 1 and res["slices"] == 3 and res["endCheck"] == "make check"
    assert "slice 2/3" in res["halted"] and "did not verify after one repair" in res["halted"]
    assert res["attemptedUnverified"] == ["s2"]
    assert res["notBuilt"] == ["s3"]                     # never built, never claimed
    labels = [c["label"] for c in out["calls"]]
    assert labels == ["slice", "build:1", "verify:1", "build:2", "verify:2", "repair:2", "verify:2"]
    assert all(c["agentType"] == "hardmode:verifier" for c in out["calls"] if c["label"].startswith("verify:"))
    assert next(c for c in out["calls"] if c["label"] == "slice")["agentType"] == "hardmode:scout"
    assert all(c["model"] for c in out["calls"]), "every agent pins a model"


def test_increment_reports_a_dead_builder_and_the_unbuilt_tail(tmp_path):
    out = run(tmp_path, "increment", {"args": {"task": "t"}, "agents": {
        "slice": {"slices": [slice_(1), slice_(2), slice_(3)], "endCheck": "e"},
        "build:1": BUILT, "verify:1": PASS, "build:2": {"__die": True},
    }})
    res = out["result"]
    assert res["completed"] == 1 and "builder for slice 2/3 did not return" in res["halted"]
    assert res["results"][1] == {"slice": "s2", "status": "builder-died"}
    assert res["attemptedUnverified"] == []
    assert res["notBuilt"] == ["s2", "s3"]               # a dead builder built nothing


def test_increment_full_pass_and_usage_error(tmp_path):
    out = run(tmp_path, "increment", {"args": "t", "agents": {
        "slice": {"slices": [slice_(1), slice_(2)], "endCheck": "e"},
        "build:*": BUILT, "verify:*": PASS,
    }})
    res = out["result"]
    assert res["halted"] is None and res["completed"] == 2 and res["notBuilt"] == [] and res["attemptedUnverified"] == []
    assert any("run the end check yourself: e" in ln for ln in out["logs"])
    assert run(tmp_path, "increment", {"args": "   ", "agents": {}})["result"]["error"].startswith("Usage:")
    out = run(tmp_path, "increment", {"args": "t", "agents": {"slice": {"__die": True}}})
    assert out["result"]["error"] == "slicer returned no slices"


def test_increment_caps_slices_and_says_so(tmp_path):
    out = run(tmp_path, "increment", {"args": "t", "agents": {
        "slice": {"slices": [slice_(i) for i in range(1, 11)], "endCheck": "e"},
        "build:*": BUILT, "verify:*": PASS,
    }})
    assert out["result"]["slices"] == 8 and out["result"]["completed"] == 8
    assert any("capped at 8" in ln and "NOT built" in ln for ln in out["logs"])


# ---- paranoid-review ----

def finding(file, title, line=None, severity="major"):
    f = {"file": file, "title": title, "detail": f"detail about {title}", "severity": severity}
    if line is not None:
        f["line"] = line
    return f


def test_paranoid_review_dedups_verifies_and_names_unreviewed_dimensions(tmp_path):
    out = run(tmp_path, "paranoid-review", {"args": "", "agents": {
        "find:correctness": {"findings": [finding("a.py", "Off by one", 3), finding("b.py", "Shared", 9, "minor")]},
        "find:integration": {"findings": [finding("b.py", "shared", 9, "minor"), finding("c.py", "Unwired", severity="critical")]},
        "find:regressions": {"__die": True},
        "find:security": {"__throw": "boom"},
        "verify:a.py": {"verdict": "confirmed", "reason": "ran it, it fails"},
        "verify:b.py": {"verdict": "refuted", "reason": "already handled"},
        "verify:c.py": {"__die": True},
    }})
    res = out["result"]
    assert res["unauditedDimensions"] == ["regressions", "security"]
    assert [f["file"] for f in res["confirmed"]] == ["a.py"] and res["confirmed"][0]["evidence"] == "ran it, it fails"
    assert [f["file"] for f in res["refuted"]] == ["b.py"]            # claimed once, not twice
    assert [f["file"] for f in res["unverified"]] == ["c.py"] and res["unverified"][0]["note"] == "verifier did not return"
    assert sum(c["label"] == "verify:b.py" for c in out["calls"]) == 1
    assert any("find:integration: 1 duplicate finding(s)" in ln for ln in out["logs"])
    assert any("find:regressions: FINDER DIED" in ln for ln in out["logs"])
    assert any("find:security: FINDER THREW (boom)" in ln for ln in out["logs"])
    assert any("UNREVIEWED dimensions: regressions, security" in ln for ln in out["logs"])
    assert all(c["agentType"] == "hardmode:verifier" for c in out["calls"] if c["label"].startswith("verify:"))
    assert all(c["agentType"] == "hardmode:scout" for c in out["calls"] if c["label"].startswith("find:"))


def test_paranoid_review_reports_unverified_when_the_budget_is_nearly_spent(tmp_path):
    out = run(tmp_path, "paranoid-review", {"args": "src/", "budgetTotal": 100_000, "spent": 80_000, "agents": {
        "find:*": {"findings": [finding("a.py", "X", 1)]},
    }})
    res = out["result"]
    assert res["unauditedDimensions"] == []
    assert res["confirmed"] == [] and [f["file"] for f in res["unverified"]] == ["a.py"]
    assert not any(c["label"].startswith("verify:") for c in out["calls"])
    assert any("UNVERIFIED" in ln for ln in out["logs"])


def test_paranoid_review_clean_diff(tmp_path):
    out = run(tmp_path, "paranoid-review", {"args": None, "agents": {"find:*": {"findings": []}}})
    res = out["result"]
    assert res == {"confirmed": [], "refuted": [], "unverified": [], "unauditedDimensions": []}
