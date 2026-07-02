import argparse
from datetime import timedelta

from .parser import parse_lines, parse_duration, filter_level, filter_window
from .stats import summarize


def main(argv=None):
    p = argparse.ArgumentParser(prog="loganalyze")
    p.add_argument("logfile")
    p.add_argument("--level", help="only count entries with this level")
    p.add_argument(
        "--last",
        help="only count entries from the last DURATION (e.g. 2h, 1h30m), "
        "relative to the newest entry",
    )
    args = p.parse_args(argv)

    with open(args.logfile) as f:
        entries = parse_lines(f)
    if args.level:
        entries = filter_level(entries, args.level)
    if args.last and entries:
        end = max(e.ts for e in entries)
        start = end - timedelta(seconds=parse_duration(args.last))
        entries = filter_window(entries, start, end)
    for level, n in sorted(summarize(entries).items()):
        print(f"{level}: {n}")


if __name__ == "__main__":
    main()
