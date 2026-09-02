#!/usr/bin/env python3
"""hardmode stats — how often does the floor actually fire? (stdlib only)

Reads the per-session rollups (sessions.jsonl, written at SessionEnd) plus the live
ledgers of sessions that have not ended yet, and prints the numbers the README used
to assert: sessions observed, sessions in which the hooks were witnessed running,
firings per hook and outcome, blocks per 100 sessions, overrides.

Usage: stats.py [--since DAYS] [--json] [--last N]
"""
import argparse
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hooks"))
from _hardmode import iter_jsonl, state_dir  # noqa: E402

FIRING = ("block", "nudge", "deny", "deny-edit", "override")


def collect(since_days, last_n):
    d = state_dir(create=False)
    cutoff = time.time() - since_days * 86400 if since_days else 0
    sessions = [s for s in iter_jsonl(os.path.join(d, "sessions.jsonl")) if int(s.get("ended", 0) or 0) >= cutoff]
    if last_n:
        sessions = sessions[-last_n:]
    live = {}
    ended = {s.get("session") for s in sessions}
    for path in glob.glob(os.path.join(d, "ledger-*.jsonl")):
        sid = os.path.basename(path)[7:-6]
        if sid in ended:
            continue
        by = {}
        for rec in iter_jsonl(path):
            k = f"{rec.get('hook')}:{rec.get('outcome')}"
            by[k] = by.get(k, 0) + 1
        live[sid] = by
    totals = {}
    for s in sessions:
        for k, v in (s.get("by_hook") or {}).items():
            totals[k] = totals.get(k, 0) + v
    for by in live.values():
        for k, v in by.items():
            totals[k] = totals.get(k, 0) + v
    witnessed = sum(1 for s in sessions if (s.get("by_hook") or {}).get("floor-check:ran"))
    fired = {k: v for k, v in totals.items() if k.split(":")[-1] in FIRING}
    blocks = sum(v for k, v in fired.items() if not k.endswith(":override"))
    n = len(sessions) + len(live)
    return {
        "state_dir": d, "sessions_ended": len(sessions), "sessions_live": len(live),
        "sessions_witnessed": witnessed,
        "blocks_per_100_sessions": round(100.0 * blocks / n, 1) if n else None,
        "overrides": totals.get("destructive-guard:override", 0),
        "by_hook": dict(sorted(totals.items())),
        "fired": dict(sorted(fired.items())),
        "last_session": sessions[-1] if sessions else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=0, help="only sessions ended in the last N days")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--last", type=int, default=0, help="only the last N ended sessions")
    a = ap.parse_args(argv)
    s = collect(a.since, a.last)
    if a.json:
        print(json.dumps(s, indent=1))
        return 0
    print(f"hardmode stats ({s['state_dir']})")
    print(f"  sessions: {s['sessions_ended']} ended, {s['sessions_live']} live; floor witnessed running in "
          f"{s['sessions_witnessed']}/{s['sessions_ended']} ended sessions")
    if s["sessions_ended"] >= 3 and s["sessions_witnessed"] == 0:
        print("  WARNING: the floor was never witnessed — hooks are not running (see /hardmode:doctor)")
    if s["fired"]:
        print("  fired: " + ", ".join(f"{k} x{v}" for k, v in s["fired"].items())
              + f"  ({s['blocks_per_100_sessions']} blocks/nudges per 100 sessions, {s['overrides']} override(s))")
    else:
        print("  fired: nothing yet — insurance whose trigger has not occurred, or a floor that is off (check 'witnessed')")
    quiet = {k: v for k, v in s["by_hook"].items() if k not in s["fired"]}
    if quiet:
        print("  armed/passed: " + ", ".join(f"{k} x{v}" for k, v in quiet.items()))
    if s["last_session"]:
        ls = s["last_session"]
        print(f"  last session: {ls.get('session')} ({ls.get('reason')}) — {ls.get('events')} event(s): "
              + (", ".join(f"{k} x{v}" for k, v in (ls.get('by_hook') or {}).items()) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
