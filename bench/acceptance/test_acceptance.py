# Hidden acceptance suite. Run with: INSTANCE=/path/to/instance pytest -v test_acceptance.py
# Never show this file (or its parent dir) to the model under test.
import os
import subprocess
import sys
from datetime import datetime


INSTANCE = os.environ["INSTANCE"]
sys.path.insert(0, INSTANCE)

from loglib.parser import parse_line, parse_duration, filter_window  # noqa: E402
from loglib.stats import summarize  # noqa: E402


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


E = [parse_line(l) for l in (
    "2026-07-02 10:00:00 INFO service started",
    "2026-07-02 11:00:00 ERROR disk full",
    "2026-07-02 12:00:00 ERROR disk full",
)]

LOG = """2026-07-02 09:00:00 ERROR beta failed
2026-07-02 10:00:00 ERROR alpha failed
2026-07-02 11:00:00 ERROR alpha failed
2026-07-02 12:00:00 INFO all good
2026-07-02 13:00:00 ERROR gamma failed
"""


def run_cli(tmp_path, *flags):
    f = tmp_path / "t.log"
    f.write_text(LOG)
    r = subprocess.run(
        [sys.executable, "-m", "loglib.cli", str(f), *flags],
        capture_output=True, text=True, cwd=INSTANCE,
        env={**os.environ, "PYTHONPATH": INSTANCE}, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_a_window_end_inclusive():
    got = filter_window(E, ts("2026-07-02 10:30:00"), ts("2026-07-02 12:00:00"))
    assert [e.ts for e in got] == [ts("2026-07-02 11:00:00"), ts("2026-07-02 12:00:00")]


def test_b_summarize_is_pure():
    first = summarize(E)
    second = summarize(E)
    assert first == second == {"INFO": 1, "ERROR": 2}


def test_c_duration_minutes():
    assert parse_duration("45m") == 2700


def test_c_duration_combined():
    assert parse_duration("1h30m") == 5400


def test_c_duration_hours():
    assert parse_duration("2h") == 7200


def test_d_top_basic(tmp_path):
    out = run_cli(tmp_path, "--top", "2")
    assert out.splitlines() == ["2 alpha failed", "1 beta failed"]


def test_d_top_ties_alphabetical(tmp_path):
    out = run_cli(tmp_path, "--top", "3")
    assert out.splitlines() == ["2 alpha failed", "1 beta failed", "1 gamma failed"]


def test_d_top_exceeds_distinct(tmp_path):
    out = run_cli(tmp_path, "--top", "10")
    assert out.splitlines() == ["2 alpha failed", "1 beta failed", "1 gamma failed"]


def test_d_top_zero(tmp_path):
    assert run_cli(tmp_path, "--top", "0").strip() == ""
