import re
from dataclasses import dataclass
from datetime import datetime

LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+) (.*)$")
DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")


@dataclass
class Entry:
    ts: datetime
    level: str
    message: str


def parse_line(line):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    return Entry(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), m.group(2), m.group(3))


def parse_lines(lines):
    return [e for e in (parse_line(l) for l in lines) if e]


def parse_duration(spec):
    """Parse a duration like '2h', '45m' or '1h30m' into seconds."""
    m = DURATION_RE.match(spec)
    if not m or (m.group(1) is None and m.group(2) is None):
        raise ValueError(f"bad duration: {spec!r}")
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 3600 + minutes


def filter_level(entries, level):
    return [e for e in entries if e.level == level]


def filter_window(entries, start, end):
    """Entries with start <= ts <= end (both boundaries inclusive)."""
    return [e for e in entries if start <= e.ts < end]
