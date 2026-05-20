from __future__ import annotations

import logging
from typing import Optional

from ai_gf.agent.llm import LLM, ChatMessage
from ai_gf.state.store import Message, Store, Summary

logger = logging.getLogger(__name__)

SUMMARY_THRESHOLD = 50  # turns since last summary before re-summarizing
SUMMARY_KEEP_RECENT = 10  # leave this many recent turns un-summarized in context

SUMMARY_PROMPT = """다음 대화 로그를 한국어로 간결히 요약해. 형식:

[사건 / 약속]
- ...

[감정 변화]
- ...

[인물 언급]
- ...

전체 길이는 300자 이내. 사실만 적고, 평가/추측은 쓰지 마. 화자 표기는 "오빠" 와 "지은" 만 사용.

대화 로그:
"""


class MemoryLog:
    def __init__(self, store: Store, llm: LLM):
        self.store = store
        self.llm = llm

    def append(self, direction: str, sender_ig_id: str, body: str, trigger_kind: Optional[str] = None) -> int:
        return self.store.record_message(direction, sender_ig_id, body, trigger_kind=trigger_kind)  # type: ignore[arg-type]

    def recent_turns(self, n: int = SUMMARY_KEEP_RECENT) -> list[Message]:
        return self.store.recent_messages(limit=n)

    def active_summary(self) -> Optional[Summary]:
        return self.store.active_summary()

    def should_summarize(self) -> bool:
        return self.store.unsummarized_message_count() >= SUMMARY_THRESHOLD

    def do_summarize(self) -> Optional[Summary]:
        """Summarize messages past the active summary, leaving the most recent
        SUMMARY_KEEP_RECENT turns out of the summary so they stay in-context.
        """
        # Pull a wider window than SUMMARY_THRESHOLD to capture all unsummarized messages.
        all_recent = self.store.recent_messages(limit=SUMMARY_THRESHOLD * 2)
        if len(all_recent) <= SUMMARY_KEEP_RECENT:
            return None

        to_summarize = all_recent[:-SUMMARY_KEEP_RECENT]
        if not to_summarize:
            return None

        log_text = "\n".join(
            f"{'오빠' if m.direction == 'in' else '지은'}: {m.body}" for m in to_summarize
        )
        prior = self.active_summary()
        prefix = f"이전 요약:\n{prior.summary_text}\n\n" if prior else ""

        prompt = prefix + SUMMARY_PROMPT + log_text
        try:
            summary_text = self.llm.quick(prompt, use_aux=True, temperature=0.2)
        except Exception as e:
            logger.warning("Summary generation failed: %s", e)
            return None

        covers_until = to_summarize[-1].id
        new_id = self.store.set_summary(summary_text, covers_until_message_id=covers_until)
        logger.info("New summary id=%d covers up to message_id=%d", new_id, covers_until)
        return self.store.active_summary()
