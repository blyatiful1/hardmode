from datetime import datetime

from loglib.parser import parse_line, parse_duration, filter_level, filter_window
from loglib.stats import summarize

L1 = "2026-07-02 10:00:00 INFO service started"
L2 = "2026-07-02 11:00:00 ERROR disk full"
L3 = "2026-07-02 12:00:00 ERROR disk full"


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def entries():
    return [parse_line(l) for l in (L1, L2, L3)]


def test_parse_line():
    e = parse_line(L2)
    assert e.level == "ERROR"
    assert e.message == "disk full"
    assert e.ts == ts("2026-07-02 11:00:00")


def test_parse_garbage():
    assert parse_line("not a log line") is None


def test_filter_level():
    assert len(filter_level(entries(), "ERROR")) == 2


def test_duration_hours():
    assert parse_duration("2h") == 7200


def test_window_end_inclusive():
    got = filter_window(entries(), ts("2026-07-02 10:30:00"), ts("2026-07-02 12:00:00"))
    assert [e.ts for e in got] == [ts("2026-07-02 11:00:00"), ts("2026-07-02 12:00:00")]


def test_summary():
    assert summarize(entries()) == {"INFO": 1, "ERROR": 2}
