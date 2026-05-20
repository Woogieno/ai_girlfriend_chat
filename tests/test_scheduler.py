from __future__ import annotations

import sqlite3
from datetime import datetime, time, timezone
from pathlib import Path

import pytest

from ai_gf.scheduler.proactive import WINDOWS, ProactiveScheduler, current_window
from ai_gf.state.store import Store


SCHEMA = Path(__file__).resolve().parent.parent / "src" / "ai_gf" / "state" / "schema.sql"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA.read_text(encoding="utf-8"))
    return Store(db)


# ---- window selection ----


def _dt(h: int, m: int) -> datetime:
    # Naive local time is fine — current_window only reads hour+minute.
    return datetime(2026, 5, 21, h, m)


@pytest.mark.parametrize("h, m, expected", [
    (8, 0, "morning"),
    (9, 30, "morning"),
    (10, 0, None),
    (12, 0, "lunch"),
    (13, 0, "lunch"),
    (13, 30, None),
    (18, 0, "evening"),
    (19, 59, "evening"),
    (20, 0, None),
    (22, 0, "night"),
    (23, 29, "night"),
    (23, 30, None),
    (7, 0, None),
    (15, 0, None),
])
def test_current_window(h: int, m: int, expected: str | None) -> None:
    assert current_window(_dt(h, m)) == expected


# ---- duplicate-window suppression ----


def test_already_sent_today_blocks_repeat(store: Store) -> None:
    class _Sentinel:
        pass

    sched = ProactiveScheduler(store, responder=_Sentinel())  # type: ignore[arg-type]
    assert sched._already_sent_today("morning") is False
    store.record_message("out", "bot", "안녕 잘 잤어?", trigger_kind="morning")
    assert sched._already_sent_today("morning") is True
    # different kind still allowed
    assert sched._already_sent_today("lunch") is False


# ---- cap behavior delegated to Responder, but ensure store count is correct ----


def test_proactive_count_only_counts_trigger_kind_outbound(store: Store) -> None:
    store.record_message("in", "owner", "hi")  # inbound, irrelevant
    store.record_message("out", "bot", "응답", trigger_kind=None)  # reactive
    store.record_message("out", "bot", "아침", trigger_kind="morning")
    store.record_message("out", "bot", "점심", trigger_kind="lunch")
    assert store.count_proactive_today() == 2
    assert store.count_outbound_today() == 3
