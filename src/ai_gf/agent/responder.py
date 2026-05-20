"""Builds and sends both reactive and proactive responses.

Single place that owns:
  - persona prompt composition
  - state-aware system prompt
  - LLM call
  - sending via the channel
  - persistent logging

Keeping all of this in one module keeps app.py thin and makes the daily-cap
guards easy to verify against the constitution.
"""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Optional

from ai_gf.agent.llm import LLM, ChatMessage
from ai_gf.agent.persona import build_system_prompt, load_persona
from ai_gf.channel.base import Channel, ChannelChallenge, InboundMessage
from ai_gf.memory.log import MemoryLog
from ai_gf.state.store import State, Store

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PROACTIVE_PROMPTS: dict[str, Path] = {
    "morning": PROMPTS_DIR / "proactive_morning.md",
    "lunch": PROMPTS_DIR / "proactive_lunch.md",
    "evening": PROMPTS_DIR / "proactive_evening.md",
    "night": PROMPTS_DIR / "proactive_night.md",
    "idle": PROMPTS_DIR / "proactive_idle.md",
}


class Responder:
    def __init__(
        self,
        store: Store,
        memory: MemoryLog,
        llm: LLM,
        channel: Channel,
        owner_ig_id: str,
        *,
        send_jitter_min_s: int = 30,
        send_jitter_max_s: int = 300,
        daily_proactive_cap: int = 20,
        daily_response_cap: int = 25,
    ):
        self.store = store
        self.memory = memory
        self.llm = llm
        self.channel = channel
        self.owner_ig_id = owner_ig_id
        self.persona = load_persona()
        self.send_jitter_min_s = send_jitter_min_s
        self.send_jitter_max_s = send_jitter_max_s
        self.daily_proactive_cap = daily_proactive_cap
        self.daily_response_cap = daily_response_cap

    # ----- public entry points -----

    def respond_to(self, inbound: InboundMessage, state: State) -> Optional[str]:
        """Generate a reactive reply for an inbound message and send it.

        State must already have been updated with the triggers' delta. Returns
        the sent body (post-sanitize) or None if cap reached.
        """
        if self.store.count_outbound_today() >= self.daily_response_cap:
            logger.warning(
                "Daily response cap %d reached — skipping reactive reply",
                self.daily_response_cap,
            )
            return None

        system = self._compose_system(state, extra_directive=None)
        # User turn = the inbound message body
        messages = [ChatMessage(role="user", content=inbound.body)]
        reply = self.llm.chat(system=system, messages=messages)
        if not reply:
            logger.warning("LLM returned empty after sanitize; skipping send")
            return None
        return self._send(reply, trigger_kind=None)

    def send_proactive(self, kind: str, state: State) -> Optional[str]:
        """Generate and send a proactive message of the given kind.

        Returns the sent body or None if cap/duplicate/empty-output suppressed.
        """
        if kind not in PROACTIVE_PROMPTS:
            raise ValueError(f"unknown proactive kind: {kind}")

        if self.store.count_proactive_today() >= self.daily_proactive_cap:
            logger.info(
                "Daily proactive cap %d reached — skipping %s",
                self.daily_proactive_cap,
                kind,
            )
            return None

        directive = PROACTIVE_PROMPTS[kind].read_text(encoding="utf-8").strip()
        system = self._compose_system(state, extra_directive=directive)
        # No user turn — we instruct the model in the system prompt itself.
        # A minimal user nudge helps the chat model produce content.
        messages = [ChatMessage(role="user", content="(자, 너의 메시지를 보내.)")]
        reply = self.llm.chat(system=system, messages=messages)
        if not reply:
            logger.warning("Empty proactive output for kind=%s after sanitize", kind)
            return None
        sent = self._send(reply, trigger_kind=kind)
        if sent is not None:
            self.store.touch_last_proactive(kind)
        return sent

    # ----- internals -----

    def _compose_system(self, state: State, *, extra_directive: Optional[str]) -> str:
        summary = self.memory.active_summary()
        recent = self.memory.recent_turns()
        return build_system_prompt(
            persona=self.persona,
            state=state,
            summary=summary,
            recent_turns=recent,
            owner_ig_id=self.owner_ig_id,
            extra_directive=extra_directive,
        )

    def _send(self, body: str, *, trigger_kind: Optional[str]) -> Optional[str]:
        # Pre-send jitter — per constitution §III, every outbound message gets
        # a randomized human-like delay.
        jitter = random.uniform(self.send_jitter_min_s, self.send_jitter_max_s)
        logger.info(
            "Sleeping %.1fs before send (jitter, trigger_kind=%s)", jitter, trigger_kind
        )
        time.sleep(jitter)

        try:
            self.channel.send(body)
        except ChannelChallenge as e:
            logger.error("Channel challenge during send — halting: %s", e)
            return None

        self.memory.append("out", "bot", body, trigger_kind=trigger_kind)
        return body
