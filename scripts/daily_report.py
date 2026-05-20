"""Print a daily snapshot of bot activity and current state.

Run from the repo root after activating the venv:
    python scripts/daily_report.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from ai_gf.config import load_settings


def main() -> int:
    s = load_settings()
    db = s.db_path
    if not db.exists():
        print(f"DB not found at {db}", file=sys.stderr)
        return 1

    with sqlite3.connect(db) as c:
        state_row = c.execute(
            "SELECT affection, jealousy, mood, last_user_msg_at, last_proactive_at, "
            "last_proactive_kind, updated_at FROM state WHERE id = 1"
        ).fetchone()

        out_today = c.execute(
            "SELECT COUNT(*) FROM messages WHERE direction='out' "
            "AND DATE(ts, 'localtime') = DATE('now', 'localtime')"
        ).fetchone()[0]
        in_today = c.execute(
            "SELECT COUNT(*) FROM messages WHERE direction='in' "
            "AND DATE(ts, 'localtime') = DATE('now', 'localtime')"
        ).fetchone()[0]
        proactive_today = c.execute(
            "SELECT trigger_kind, COUNT(*) FROM messages "
            "WHERE direction='out' AND trigger_kind IS NOT NULL "
            "AND DATE(ts, 'localtime') = DATE('now', 'localtime') "
            "GROUP BY trigger_kind"
        ).fetchall()
        recent_triggers = c.execute(
            "SELECT ts, affection, jealousy, mood, reason "
            "FROM state_snapshots ORDER BY id DESC LIMIT 10"
        ).fetchall()
        summary = c.execute(
            "SELECT ts, summary_text FROM summary WHERE superseded = 0 "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last5 = c.execute(
            "SELECT ts, direction, body, trigger_kind FROM messages "
            "ORDER BY id DESC LIMIT 5"
        ).fetchall()

    print("=" * 60)
    print("ai_gf daily report")
    print("=" * 60)
    print()
    print("STATE")
    print(f"  affection: {state_row[0]}/100")
    print(f"  jealousy : {state_row[1]}/100")
    print(f"  mood     : {state_row[2]}")
    print(f"  last user msg : {state_row[3]}")
    print(f"  last proactive: {state_row[4]} ({state_row[5]})")
    print(f"  updated_at    : {state_row[6]}")
    print()
    print("TODAY")
    print(f"  inbound : {in_today}")
    print(f"  outbound: {out_today}")
    if proactive_today:
        print("  proactive breakdown:")
        for kind, cnt in proactive_today:
            print(f"    {kind:10s} {cnt}")
    print()
    print("RECENT STATE TRANSITIONS (newest first)")
    for ts, aff, jea, mood, reason in recent_triggers:
        print(f"  {ts}  a={aff:3d} j={jea:3d} {mood:8s}  {reason}")
    print()
    if summary:
        print("ACTIVE SUMMARY")
        print(f"  ({summary[0]})")
        for line in summary[1].splitlines():
            print(f"  {line}")
        print()
    print("LAST 5 MESSAGES (newest first)")
    for ts, direction, body, trigger in last5:
        marker = f"[{trigger}]" if trigger else ""
        print(f"  {ts}  {direction:3s} {marker} {body[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
