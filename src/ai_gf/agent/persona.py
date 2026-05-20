from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from ai_gf.state.store import Message, State, Summary

PERSONA_FILE = Path(__file__).resolve().parent.parent / "prompts" / "persona.md"


def load_persona(path: Path = PERSONA_FILE) -> str:
    return path.read_text(encoding="utf-8").strip()


def _time_of_day(hour: int) -> str:
    if hour < 5:
        return "새벽"
    if hour < 11:
        return "아침"
    if hour < 14:
        return "점심"
    if hour < 18:
        return "오후"
    if hour < 22:
        return "저녁"
    return "밤"


def _format_now(now_utc: datetime, tz_name: str) -> tuple[str, str]:
    """Return (HH:MM, time-of-day label) in the local timezone."""
    local = now_utc.astimezone(ZoneInfo(tz_name))
    return local.strftime("%H:%M"), _time_of_day(local.hour)


def _format_idle(last_user_msg_at: Optional[datetime], now: Optional[datetime] = None) -> str:
    if last_user_msg_at is None:
        return "아직 오빠 메시지를 받은 적 없음"
    now = now or datetime.now(timezone.utc)
    delta = now - last_user_msg_at
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 1:
        return "방금 전"
    if total_minutes < 60:
        return f"{total_minutes}분 전"
    hours = total_minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    return f"{days}일 전"


def _format_recent_turns(messages: list[Message], owner_ig_id: str) -> str:
    if not messages:
        return "(최근 대화 없음)"
    lines = []
    for m in messages:
        speaker = "오빠" if m.direction == "in" else "지은"
        lines.append(f"{speaker}: {m.body}")
    return "\n".join(lines)


def build_system_prompt(
    persona: str,
    state: State,
    summary: Optional[Summary],
    recent_turns: list[Message],
    owner_ig_id: str,
    now: Optional[datetime] = None,
    extra_directive: Optional[str] = None,
    timezone_name: str = "Asia/Seoul",
) -> str:
    """Compose the full system prompt: persona + state + summary + recent + optional directive.

    The persona MUST be at the top and unmodified per constitution §I.
    """
    now_utc = now or datetime.now(timezone.utc)
    hhmm, tod = _format_now(now_utc, timezone_name)

    sections = [persona, "", "---", "", "# 현재 상황", ""]
    sections.append(f"- 지금 시각: **{hhmm}** ({tod}) — {timezone_name}")
    sections.append(f"- 인사·대화는 반드시 이 시간대에 맞게. (예: 밤에 '잘잤어?' 같은 아침 인사 금지)")
    sections += ["", "# 현재 너의 상태", ""]
    sections.append(f"- 기분(mood): **{state.mood}**")
    sections.append(f"- 오빠에 대한 애정(affection): {state.affection}/100")
    sections.append(f"- 질투 수준(jealousy): {state.jealousy}/100")
    sections.append(f"- 오빠가 마지막으로 메시지 보낸 시각: {_format_idle(state.last_user_msg_at, now=now_utc)}")

    sections += ["", "# 이전 대화 요약", ""]
    sections.append(summary.summary_text if summary else "(아직 요약된 이전 대화 없음)")

    sections += ["", "# 최근 대화", ""]
    sections.append(_format_recent_turns(recent_turns, owner_ig_id))

    if extra_directive:
        sections += ["", "# 지금 너가 해야 할 행동", "", extra_directive]

    return "\n".join(sections)
