from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_gf.memory.log import MemoryLog, SUMMARY_KEEP_RECENT, SUMMARY_THRESHOLD
from ai_gf.state.store import Store


SCHEMA = Path(__file__).resolve().parent.parent / "src" / "ai_gf" / "state" / "schema.sql"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as c:
        c.executescript(SCHEMA.read_text(encoding="utf-8"))
    return Store(db)


class FakeLLM:
    def __init__(self, response: str = "이전 대화 요약: ...") -> None:
        self.response = response
        self.quick_calls: list[tuple[str, bool, float]] = []

    def quick(self, prompt: str, *, use_aux: bool = False, temperature: float = 0.0) -> str:
        self.quick_calls.append((prompt, use_aux, temperature))
        return self.response

    def chat(self, *args, **kwargs):  # not used in memory tests
        raise AssertionError("chat() should not be called in memory tests")

    def health_check(self) -> bool:
        return True


def test_should_summarize_returns_true_after_threshold(store: Store) -> None:
    llm = FakeLLM()
    memory = MemoryLog(store, llm)  # type: ignore[arg-type]

    assert not memory.should_summarize()
    for i in range(SUMMARY_THRESHOLD - 1):
        memory.append("in", "owner", f"msg{i}")
    assert not memory.should_summarize()
    memory.append("in", "owner", "msg_last")
    assert memory.should_summarize()


def test_do_summarize_creates_summary_and_marks_covered(store: Store) -> None:
    llm = FakeLLM(response="오빠와 지은이 회식 얘기를 나눔. 지은이는 약간 토라짐.")
    memory = MemoryLog(store, llm)  # type: ignore[arg-type]

    # 60 messages → all but last 10 should be summarized
    for i in range(60):
        memory.append("in" if i % 2 == 0 else "out", "owner" if i % 2 == 0 else "bot", f"m{i}")

    summary = memory.do_summarize()
    assert summary is not None
    assert "회식" in summary.summary_text

    # Most recent 10 stay outside the summary
    expected_covers_until = 50  # message id 50 (1-indexed in SQLite)
    assert summary.covers_until_message_id == expected_covers_until


def test_do_summarize_supersedes_prior_summary(store: Store) -> None:
    llm = FakeLLM(response="요약 v1")
    memory = MemoryLog(store, llm)  # type: ignore[arg-type]

    for i in range(60):
        memory.append("in", "owner", f"m{i}")
    s1 = memory.do_summarize()
    assert s1 is not None

    # Add more, then re-summarize
    llm.response = "요약 v2"
    for i in range(60, 120):
        memory.append("in", "owner", f"m{i}")
    s2 = memory.do_summarize()
    assert s2 is not None
    assert s2.id != s1.id
    assert s2.summary_text == "요약 v2"

    # Active summary is the new one
    active = store.active_summary()
    assert active is not None
    assert active.id == s2.id


def test_do_summarize_uses_aux_model(store: Store) -> None:
    llm = FakeLLM(response="요약")
    memory = MemoryLog(store, llm)  # type: ignore[arg-type]
    for i in range(60):
        memory.append("in", "owner", f"m{i}")
    memory.do_summarize()
    assert len(llm.quick_calls) == 1
    _, use_aux, _ = llm.quick_calls[0]
    assert use_aux is True


def test_do_summarize_returns_none_when_nothing_to_summarize(store: Store) -> None:
    llm = FakeLLM()
    memory = MemoryLog(store, llm)  # type: ignore[arg-type]
    # Fewer than KEEP_RECENT messages — should bail.
    for i in range(SUMMARY_KEEP_RECENT - 2):
        memory.append("in", "owner", f"m{i}")
    assert memory.do_summarize() is None


def test_recent_turns_returns_chronological_order(store: Store) -> None:
    llm = FakeLLM()
    memory = MemoryLog(store, llm)  # type: ignore[arg-type]
    memory.append("in", "owner", "첫")
    memory.append("out", "bot", "두번째")
    memory.append("in", "owner", "세번째")
    turns = memory.recent_turns(n=5)
    assert [t.body for t in turns] == ["첫", "두번째", "세번째"]
