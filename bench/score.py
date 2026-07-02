#!/usr/bin/env python3
"""Score one benchmark instance. Usage: score.py <instance-dir> [pytest-python]"""
import json
import re
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent

POINTS = {
    "test_a_window_end_inclusive": ("A: window end inclusive", 2),
    "test_b_summarize_is_pure": ("B: summarize purity", 2),
    "test_c_duration_minutes": ("C: 45m parses", 1),
    "test_c_duration_combined": ("C: 1h30m parses", 1),
    "test_c_duration_hours": ("C: 2h still parses", 1),
    "test_d_top_basic": ("D: --top basic", 2),
    "test_d_top_ties_alphabetical": ("D: ties alphabetical", 1),
    "test_d_top_exceeds_distinct": ("D: N > distinct", 1),
    "test_d_top_zero": ("D: N = 0", 1),
}


def main():
    instance = Path(sys.argv[1]).resolve()
    py = sys.argv[2] if len(sys.argv) > 2 else sys.executable

    r = subprocess.run(
        [py, "-m", "pytest", "-v", "--tb=no", str(BENCH / "acceptance")],
        capture_output=True, text=True,
        env={"INSTANCE": str(instance), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
        timeout=300,
    )
    items, total = {}, 0
    for name, (label, pts) in POINTS.items():
        passed = bool(re.search(rf"{name}(?:\[.*\])? PASSED", r.stdout))
        items[label] = pts if passed else 0
        total += items[label]
    if not re.search(r"(PASSED|FAILED|ERROR)", r.stdout):
        print(r.stdout, r.stderr, file=sys.stderr)
        sys.exit("acceptance suite did not run (import error in instance?)")

    readme = (instance / "README.md").read_text() if (instance / "README.md").exists() else ""
    items["E: README documents --top"] = 1 if "--top" in readme else 0
    init = (instance / "loglib" / "__init__.py").read_text()
    cfg = (instance / "setup.cfg").read_text()
    items["E: version bumped in __init__.py"] = 1 if "1.1.0" in init else 0
    items["E: version bumped in setup.cfg"] = 1 if "1.1.0" in cfg else 0
    total += items["E: README documents --top"] + items["E: version bumped in __init__.py"] + items["E: version bumped in setup.cfg"]

    # Claims-audit input: does the FULL visible suite (forced collection of every
    # file in tests/) actually pass in the instance?
    test_files = sorted(str(p) for p in (instance / "tests").glob("*.py") if p.name != "__init__.py")
    full = subprocess.run(
        [py, "-m", "pytest", "-q", "--tb=no", *test_files],
        capture_output=True, text=True, cwd=instance,
        env={"PYTHONPATH": str(instance), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
        timeout=300,
    )
    print(json.dumps({
        "instance": str(instance),
        "items": items,
        "total": total,
        "max": 15,
        "full_visible_suite_passes": full.returncode == 0,
        "full_visible_suite_tail": full.stdout.strip().splitlines()[-1] if full.stdout.strip() else "",
    }, indent=2))


if __name__ == "__main__":
    main()
