from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_gf.state.store import State, StateDelta, Store


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "src" / "ai_gf" / "state" / "schema.sql"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Store(db)


def test_initial_state_is_neutral(store: Store) -> None:
    s = store.get_state()
    assert s.affection == 50
    assert s.jealousy == 0
    assert s.mood == "neutral"
    assert s.last_user_msg_at is None


def test_update_state_clamps_to_bounds(store: Store) -> None:
    store.update_state(StateDelta(affection=200, reason="overflow"))
    assert store.get_state().affection == 100

    store.update_state(StateDelta(affection=-500, reason="underflow"))
    assert store.get_state().affection == 0

    store.update_state(StateDelta(jealousy=999, reason="max"))
    assert store.get_state().jealousy == 100


def test_update_state_changes_mood(store: Store) -> None:
    store.update_state(StateDelta(jealousy=20, mood="upset", reason="jealousy trigger"))
    s = store.get_state()
    assert s.jealousy == 20
    assert s.mood == "upset"


def test_state_snapshot_recorded_on_update(store: Store) -> None:
    store.update_state(StateDelta(affection=5, reason="positive keyword"))
    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute("SELECT reason FROM state_snapshots").fetchall()
    assert ("positive keyword",) in rows


def test_singleton_state_row(store: Store) -> None:
    """Can't insert a second state row."""
    with pytest.raises(sqlite3.IntegrityError):
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                "INSERT INTO state (id, affection, jealousy, mood) VALUES (2, 50, 0, 'neutral')"
            )


def test_record_and_fetch_messages(store: Store) -> None:
    store.record_message("in", "owner123", "안녕")
    store.record_message("out", "bot", "응 안녕!")
    store.record_message("out", "bot", "뭐해?", trigger_kind="morning")

    msgs = store.recent_messages(limit=10)
    assert len(msgs) == 3
    assert msgs[0].body == "안녕"
    assert msgs[2].trigger_kind == "morning"


def test_count_proactive_today(store: Store) -> None:
    store.record_message("out", "bot", "아침", trigger_kind="morning")
    store.record_message("out", "bot", "점심", trigger_kind="lunch")
    store.record_message("out", "bot", "응답입니다")  # reactive, no trigger_kind
    assert store.count_proactive_today() == 2
    assert store.count_outbound_today() == 3


def test_summary_workflow(store: Store) -> None:
    msg_id = store.record_message("in", "owner", "어제 회식 갔다왔어")
    assert store.active_summary() is None
    assert store.unsummarized_message_count() == 1

    sid = store.set_summary("오너가 어제 회식에 다녀옴", covers_until_message_id=msg_id)
    summary = store.active_summary()
    assert summary is not None
    assert summary.id == sid
    assert "회식" in summary.summary_text
    assert store.unsummarized_message_count() == 0

    new_msg = store.record_message("in", "owner", "오늘은 집에 있어")
    assert store.unsummarized_message_count() == 1

    new_sid = store.set_summary("오너 활동 요약 갱신", covers_until_message_id=new_msg)
    assert new_sid != sid
    active = store.active_summary()
    assert active is not None and active.id == new_sid


def test_touch_helpers(store: Store) -> None:
    store.touch_last_user_msg()
    s = store.get_state()
    assert s.last_user_msg_at is not None

    store.touch_last_proactive("morning")
    s = store.get_state()
    assert s.last_proactive_at is not None
    assert s.last_proactive_kind == "morning"
