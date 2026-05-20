from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional

Direction = Literal["in", "out"]
Mood = Literal["happy", "neutral", "upset", "cold"]


@dataclass
class State:
    affection: int
    jealousy: int
    mood: Mood
    last_user_msg_at: Optional[datetime]
    last_proactive_at: Optional[datetime]
    last_proactive_kind: Optional[str]
    updated_at: datetime


@dataclass
class StateDelta:
    affection: int = 0
    jealousy: int = 0
    mood: Optional[Mood] = None
    reason: str = ""


@dataclass
class Message:
    id: int
    ts: datetime
    direction: Direction
    sender_ig_id: str
    body: str
    trigger_kind: Optional[str]


@dataclass
class Summary:
    id: int
    ts: datetime
    summary_text: str
    covers_until_message_id: int


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    # SQLite stores CURRENT_TIMESTAMP as "YYYY-MM-DD HH:MM:SS" (UTC, no tz suffix)
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    # ---------- state ----------

    def get_state(self) -> State:
        with self._conn() as c:
            row = c.execute(
                "SELECT affection, jealousy, mood, last_user_msg_at, "
                "last_proactive_at, last_proactive_kind, updated_at "
                "FROM state WHERE id = 1"
            ).fetchone()
        return State(
            affection=row[0],
            jealousy=row[1],
            mood=row[2],
            last_user_msg_at=_parse_ts(row[3]),
            last_proactive_at=_parse_ts(row[4]),
            last_proactive_kind=row[5],
            updated_at=_parse_ts(row[6]) or datetime.now(timezone.utc),
        )

    def update_state(self, delta: StateDelta) -> State:
        """Apply a delta atomically. Clamps affection/jealousy to [0, 100].

        Records a snapshot in state_snapshots with the supplied reason.
        Returns the new state.
        """
        with self._conn() as c:
            c.execute("BEGIN")
            row = c.execute(
                "SELECT affection, jealousy, mood FROM state WHERE id = 1"
            ).fetchone()
            new_affection = _clamp(row[0] + delta.affection)
            new_jealousy = _clamp(row[1] + delta.jealousy)
            new_mood = delta.mood or row[2]
            c.execute(
                "UPDATE state SET affection = ?, jealousy = ?, mood = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (new_affection, new_jealousy, new_mood),
            )
            c.execute(
                "INSERT INTO state_snapshots (affection, jealousy, mood, reason) "
                "VALUES (?, ?, ?, ?)",
                (new_affection, new_jealousy, new_mood, delta.reason),
            )
            c.execute("COMMIT")
        return self.get_state()

    def touch_last_user_msg(self) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE state SET last_user_msg_at = CURRENT_TIMESTAMP WHERE id = 1"
            )

    def touch_last_proactive(self, kind: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE state SET last_proactive_at = CURRENT_TIMESTAMP, "
                "last_proactive_kind = ? WHERE id = 1",
                (kind,),
            )

    # ---------- messages ----------

    def record_message(
        self,
        direction: Direction,
        sender_ig_id: str,
        body: str,
        trigger_kind: Optional[str] = None,
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO messages (direction, sender_ig_id, body, trigger_kind) "
                "VALUES (?, ?, ?, ?)",
                (direction, sender_ig_id, body, trigger_kind),
            )
            return cur.lastrowid or 0

    def recent_messages(self, limit: int = 10) -> list[Message]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, ts, direction, sender_ig_id, body, trigger_kind "
                "FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Message(
                id=r[0],
                ts=_parse_ts(r[1]) or datetime.now(timezone.utc),
                direction=r[2],
                sender_ig_id=r[3],
                body=r[4],
                trigger_kind=r[5],
            )
            for r in reversed(rows)
        ]

    def count_outbound_today(self) -> int:
        """Outbound messages sent today (UTC date — caller may want timezone awareness)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM messages WHERE direction = 'out' "
                "AND DATE(ts) = DATE('now')"
            ).fetchone()
        return int(row[0])

    def count_proactive_today(self) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM messages WHERE direction = 'out' "
                "AND trigger_kind IS NOT NULL AND DATE(ts) = DATE('now')"
            ).fetchone()
        return int(row[0])

    # ---------- summary ----------

    def active_summary(self) -> Optional[Summary]:
        with self._conn() as c:
            row = c.execute(
                "SELECT id, ts, summary_text, covers_until_message_id "
                "FROM summary WHERE superseded = 0 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return Summary(
            id=row[0],
            ts=_parse_ts(row[1]) or datetime.now(timezone.utc),
            summary_text=row[2],
            covers_until_message_id=row[3],
        )

    def set_summary(self, summary_text: str, covers_until_message_id: int) -> int:
        with self._conn() as c:
            c.execute("BEGIN")
            c.execute("UPDATE summary SET superseded = 1 WHERE superseded = 0")
            cur = c.execute(
                "INSERT INTO summary (summary_text, covers_until_message_id) "
                "VALUES (?, ?)",
                (summary_text, covers_until_message_id),
            )
            c.execute("COMMIT")
            return cur.lastrowid or 0

    def unsummarized_message_count(self) -> int:
        """How many messages exist past the active summary's covers_until_message_id."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM messages WHERE id > "
                "COALESCE((SELECT covers_until_message_id FROM summary "
                "WHERE superseded = 0 ORDER BY id DESC LIMIT 1), 0)"
            ).fetchone()
        return int(row[0])
