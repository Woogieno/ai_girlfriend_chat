from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_gf.agent.triggers import (
    HIGH_JEALOUSY,
    MEDIUM_JEALOUSY,
    Analysis,
    analyze,
    hourly_decay,
)
from ai_gf.state.store import State


def _state(mood="neutral", affection=50, jealousy=0) -> State:
    return State(
        affection=affection,
        jealousy=jealousy,
        mood=mood,
        last_user_msg_at=None,
        last_proactive_at=None,
        last_proactive_kind=None,
        updated_at=datetime.now(timezone.utc),
    )


# ---- jealousy ----


def test_high_jealousy_keyword_triggers_upset_mood() -> None:
    a = analyze("오늘 다른 여자랑 영화 봤어", _state(), llm=None)
    assert a.delta.jealousy == 20
    assert a.delta.mood == "upset"
    assert any(t in a.matched for t in HIGH_JEALOUSY)


def test_medium_jealousy_alone_does_not_immediately_become_cold() -> None:
    a = analyze("오늘 회식이라 늦게 끝났어", _state(), llm=None)
    assert a.delta.jealousy == 12  # MEDIUM (12) alone, no LOW escalation (jealousy starts at 0)
    # 0 + 12 = 12 → still neutral (threshold 20 for upset)
    assert a.delta.mood is None


def test_low_jealousy_escalates_only_when_already_jealous() -> None:
    # Already moderately jealous → "늦게" alone adds 5
    a = analyze("오빠 늦게 와", _state(jealousy=25, mood="upset"), llm=None)
    assert a.delta.jealousy == 5
    # 25 + 5 = 30, still upset (no transition)
    assert a.delta.mood is None


def test_low_jealousy_ignored_when_not_jealous() -> None:
    a = analyze("오빠 늦게 와", _state(jealousy=0), llm=None)
    assert a.delta.jealousy == 0


def test_cold_threshold() -> None:
    a = analyze("다른 여자랑 영화 봤어", _state(jealousy=50), llm=None)
    # 50 + 20 = 70 → cold (threshold 55)
    assert a.delta.mood == "cold"


# ---- affection ----


def test_positive_words_bump_affection() -> None:
    a = analyze("사랑해 보고싶어", _state(), llm=None)
    assert a.delta.affection == 5


def test_negative_words_lower_affection() -> None:
    a = analyze("아 너무 짜증나 귀찮아", _state(), llm=None)
    assert a.delta.affection == -5


def test_sad_message_slight_affection_bump() -> None:
    a = analyze("오늘 너무 힘들어 ㅠ", _state(), llm=None)
    assert a.delta.affection == 2


def test_happy_mood_at_high_affection_low_jealousy() -> None:
    s = _state(affection=66, jealousy=0)
    a = analyze("사랑해", s, llm=None)
    # 66 + 5 = 71 affection, 0 jealousy → happy
    assert a.delta.mood == "happy"


# ---- mixed / edge cases ----


def test_high_and_medium_jealousy_are_dampened_together() -> None:
    """When both high and medium fire, medium bumps by 8 not 12 to avoid overshoot."""
    a = analyze("다른 여자랑 회식 갔다 왔어", _state(), llm=None)
    # high (20) + medium (8 dampened) = 28
    assert a.delta.jealousy == 28


def test_no_trigger_returns_no_change() -> None:
    a = analyze("오늘 코딩 좀 했어", _state(), llm=None)
    assert a.delta.affection == 0
    assert a.delta.jealousy == 0
    assert a.delta.mood is None
    assert a.matched == []


# ---- aux LLM fallback ----


class StubLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def quick(self, prompt: str, *, use_aux: bool = False, temperature: float = 0.0) -> str:
        self.calls.append(prompt)
        return self.response


def test_aux_llm_invoked_only_when_no_keyword_match() -> None:
    llm = StubLLM("75")
    a = analyze("그 사람이랑 같이 있었어 좀 미묘했어", _state(), llm=llm)  # type: ignore[arg-type]
    assert len(llm.calls) == 1
    assert a.aux_jealousy_score == 75
    assert a.delta.jealousy == 12


def test_aux_llm_not_called_when_keyword_already_matched() -> None:
    llm = StubLLM("99")
    analyze("다른 여자랑 영화", _state(), llm=llm)  # type: ignore[arg-type]
    assert llm.calls == []


def test_aux_llm_low_score_does_not_trigger() -> None:
    llm = StubLLM("20")
    a = analyze("그 카페 어땠어 친구가 추천해줬어", _state(), llm=llm)  # type: ignore[arg-type]
    assert a.aux_jealousy_score == 20
    assert a.delta.jealousy == 0


def test_aux_llm_garbage_response_handled() -> None:
    llm = StubLLM("음...뭐라고 말해야 할까")
    a = analyze("얘기 좀 들어줘", _state(), llm=llm)  # type: ignore[arg-type]
    # No int parseable → score None → no trigger
    assert a.aux_jealousy_score is None
    assert a.delta.jealousy == 0


# ---- decay ----


def test_hourly_decay_reduces_jealousy() -> None:
    d = hourly_decay(_state(jealousy=40, mood="upset"))
    assert d.jealousy == -5


def test_hourly_decay_recovers_mood_when_jealousy_drops() -> None:
    # upset at jealousy=22, decay to 17 should become neutral (threshold 20)
    d = hourly_decay(_state(jealousy=22, mood="upset"))
    assert d.mood == "neutral"


def test_hourly_decay_noop_when_no_jealousy() -> None:
    d = hourly_decay(_state(jealousy=0))
    assert d.jealousy == 0
    assert d.mood is None
