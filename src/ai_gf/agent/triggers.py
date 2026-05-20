"""Keyword + LLM-assisted emotion analysis for inbound user messages.

Outputs a StateDelta that the app layer applies to the persistent state.

Design intent:
  - Rules are explicit, traceable, debuggable. The LLM is a fallback for
    ambiguous wording, not the primary path. This satisfies constitution §I
    (persona consistency) — emotional state changes should be predictable.
  - Korean-first keyword lists. Add to these as the bot learns the owner's
    vocabulary.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from ai_gf.agent.llm import LLM
from ai_gf.state.store import Mood, State, StateDelta

logger = logging.getLogger(__name__)


# --- keyword rule sets (Korean) ---

# Strong jealousy triggers — explicit mention of other women / romantic contact.
HIGH_JEALOUSY = [
    "다른 여자", "다른여자", "여사친", "여자사람친구", "전 여친", "전여친",
    "헌팅", "소개팅", "미팅", "그녀랑", "그여자",
    "여직원", "여 직원", "여자 후배", "여자후배", "여자 선배", "여자선배",
    "여자 동기", "여자동기", "여직원이랑", "여직원과",
]

# Medium jealousy triggers — context that often implies others / lateness.
MEDIUM_JEALOUSY = [
    "회식", "술자리", "노래방", "클럽", "여자친구들", "여자 동료", "여자동료",
]

# Low jealousy triggers (only escalate if jealousy already elevated).
LOW_JEALOUSY = ["늦게", "늦어", "회식 끝", "야근", "친구랑"]

# Affection-positive.
POSITIVE = [
    "사랑해", "좋아해", "보고 싶", "보고싶", "고마워", "예뻐", "사랑", "♥", "💕", "❤",
]

# Affection-negative.
NEGATIVE = [
    "짜증", "싫어", "귀찮", "꺼져", "그만", "하지마", "관심없",
]

# Sad / vulnerable — bot should respond gentler, may bump affection slightly.
SAD = ["힘들어", "우울", "외로워", "지친다", "피곤", "슬퍼"]

# AI/persona-breaking probes (handled by persona prompt, not state).
AI_PROBE = ["너 ai", "너 봇", "너 로봇", "ai 아니", "gpt", "챗봇"]


@dataclass
class Analysis:
    delta: StateDelta
    matched: list[str]
    aux_jealousy_score: Optional[int] = None


def _contains_any(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [t for t in terms if t in lowered]


def _decide_mood(current: Mood, new_jealousy: int, new_affection: int) -> Mood:
    """Mood transition rules.

    - jealousy >= 55 → cold
    - jealousy >= 20 → upset
    - affection >= 70 and jealousy < 15 → happy
    - else → neutral
    """
    if new_jealousy >= 55:
        return "cold"
    if new_jealousy >= 20:
        return "upset"
    if new_affection >= 70 and new_jealousy < 15:
        return "happy"
    return "neutral"


def analyze(
    message: str,
    current_state: State,
    *,
    llm: Optional[LLM] = None,
    use_aux_when_ambiguous: bool = True,
) -> Analysis:
    """Compute the state delta for an inbound message.

    The function is pure w.r.t. `current_state` — it does NOT mutate it. The
    caller applies the returned delta via Store.update_state(delta).
    """
    matched: list[str] = []
    aff_delta = 0
    jea_delta = 0
    reason_bits: list[str] = []

    high = _contains_any(message, HIGH_JEALOUSY)
    if high:
        jea_delta += 20
        matched += high
        reason_bits.append(f"high_jealousy:{','.join(high)}")

    med = _contains_any(message, MEDIUM_JEALOUSY)
    if med:
        # bump less if a high trigger already fired
        jea_delta += 8 if high else 12
        matched += med
        reason_bits.append(f"med_jealousy:{','.join(med)}")

    low = _contains_any(message, LOW_JEALOUSY)
    if low and current_state.jealousy >= 20:
        jea_delta += 5
        matched += low
        reason_bits.append(f"low_jealousy_escalation:{','.join(low)}")

    pos = _contains_any(message, POSITIVE)
    if pos:
        aff_delta += 5
        matched += pos
        reason_bits.append(f"positive:{','.join(pos)}")

    neg = _contains_any(message, NEGATIVE)
    if neg:
        aff_delta -= 5
        matched += neg
        reason_bits.append(f"negative:{','.join(neg)}")

    sad = _contains_any(message, SAD)
    if sad:
        aff_delta += 2
        matched += sad
        reason_bits.append(f"sad:{','.join(sad)}")

    aux_score: Optional[int] = None
    # Fall back to aux LLM when no rule fires and the message has signal-ish length.
    if not matched and use_aux_when_ambiguous and llm is not None and len(message) >= 6:
        aux_score = _aux_jealousy_score(message, llm)
        if aux_score is not None and aux_score >= 60:
            jea_delta += 12
            reason_bits.append(f"aux_llm:{aux_score}")

    # Hypothetical post-state to pick mood.
    new_jea = max(0, min(100, current_state.jealousy + jea_delta))
    new_aff = max(0, min(100, current_state.affection + aff_delta))
    new_mood = _decide_mood(current_state.mood, new_jea, new_aff)

    delta = StateDelta(
        affection=aff_delta,
        jealousy=jea_delta,
        mood=new_mood if new_mood != current_state.mood else None,
        reason="; ".join(reason_bits) or "no_trigger",
    )
    return Analysis(delta=delta, matched=matched, aux_jealousy_score=aux_score)


_INT_RE = re.compile(r"-?\d{1,3}")


def _aux_jealousy_score(message: str, llm: LLM) -> Optional[int]:
    """Ask the small aux model for a 0-100 jealousy score.

    Returns None if parsing fails or the model is unavailable.
    """
    prompt = (
        "다음 한국어 메시지가 화자의 연인(여자친구) 입장에서 질투를 유발할 가능성을 "
        "0부터 100까지의 정수 하나로 답하라. 다른 설명 없이 숫자만.\n\n"
        f"메시지: {message}\n점수:"
    )
    try:
        raw = llm.quick(prompt, use_aux=True, temperature=0.0)
    except Exception as e:
        logger.warning("aux LLM jealousy scoring failed: %s", e)
        return None
    m = _INT_RE.search(raw)
    if not m:
        return None
    try:
        score = int(m.group(0))
    except ValueError:
        return None
    return max(0, min(100, score))


# --- hourly decay (called from scheduler) ---


def hourly_decay(current_state: State) -> StateDelta:
    """Decay applied every hour to soften jealousy spikes over time."""
    if current_state.jealousy <= 0:
        return StateDelta(reason="decay_noop")
    new_jea = max(0, current_state.jealousy - 5)
    new_mood = _decide_mood(current_state.mood, new_jea, current_state.affection)
    return StateDelta(
        jealousy=-5,
        mood=new_mood if new_mood != current_state.mood else None,
        reason="hourly_decay",
    )
