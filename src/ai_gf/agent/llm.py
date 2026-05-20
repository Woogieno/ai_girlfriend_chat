from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, Optional

import httpx
import ollama

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant"]

# Catches CJK ideographs (Chinese/Japanese) — Korean Hangul is in a separate block,
# so this won't strip Korean text.
_NON_KOREAN_CJK = re.compile(r"[㐀-鿿豈-﫿]+")
# Fullwidth (CJK-style) punctuation. Qwen leaks these at message ends.
_FULLWIDTH_PUNCT = re.compile(
    "[！，．：；？、。「」『』"
    "（）【】《》〈〉…・]"
)
# Stray ASCII letter runs (English leakage). Allows single letters in slang/emoticons.
_ASCII_RUN = re.compile(r"[A-Za-z]{2,}")
# Multi-paragraph guard: drop everything after a "---" divider the model might add.
_DIVIDER = re.compile(r"\n-{3,}.*", re.DOTALL)
# Chat-template tokens that occasionally leak in Qwen output.
_CHAT_TOKENS = re.compile(r"<\|[^|>]*\|>")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")

# 호칭 leak 자동 치환 (페르소나 §I 일관성 보강).
# 한글 자모가 앞에 없을 때만 매칭 → "어너가" 같은 우연 일치 방지.
# "너무", "너희", "너네" 같이 호칭 외 단어는 건드리지 않음 (조사 화이트리스트).
_HOCHING_RULES = [
    # "네가"는 "너"의 주격 변형 — 명확히 2인칭일 때만
    (re.compile(r"(?<![가-힣])네가(?![가-힣])"), "오빠가"),
    # "너 + 조사" 패턴
    (re.compile(r"(?<![가-힣])너가(?![가-힣])"), "오빠가"),
    (re.compile(r"(?<![가-힣])너는(?![가-힣])"), "오빠는"),
    (re.compile(r"(?<![가-힣])너도(?![가-힣])"), "오빠도"),
    (re.compile(r"(?<![가-힣])너의(?![가-힣])"), "오빠의"),
    (re.compile(r"(?<![가-힣])너를(?![가-힣])"), "오빠를"),
    (re.compile(r"(?<![가-힣])너랑(?![가-힣])"), "오빠랑"),
    (re.compile(r"(?<![가-힣])너한테(?![가-힣])"), "오빠한테"),
    (re.compile(r"(?<![가-힣])너에게(?![가-힣])"), "오빠에게"),
    (re.compile(r"(?<![가-힣])너만(?![가-힣])"), "오빠만"),
    (re.compile(r"(?<![가-힣])너랑은(?![가-힣])"), "오빠랑은"),
    # "당신"은 거리감 호칭 → 오빠로 통일
    (re.compile(r"(?<![가-힣])당신(?![가-힣])"), "오빠"),
]


def replace_hoching(text: str) -> str:
    """호칭 leak 보수적 치환. 단어 경계 매칭으로 false positive 최소화."""
    for pat, repl in _HOCHING_RULES:
        text = pat.sub(repl, text)
    return text


def _strip_speaker_prefix(line: str) -> str:
    """Drop a leading "지은:" / "지은 :" / "Jieun:" prefix if present."""
    for prefix in ("지은:", "지은 :", "Jieun:", "Bot:", "ai:", "AI:"):
        if line.startswith(prefix):
            return line[len(prefix):].lstrip()
    return line


def _strip_wrapping_quotes(text: str) -> str:
    """Remove a single pair of matching outer quotes if the whole text is wrapped."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "「", "『"):
        return text[1:-1].strip()
    return text


# Lines that look like meta/instruction echoes (model talking about itself).
_META_INDICATORS = (
    "해석하지",
    "출력해",
    "출력하지",
    "지은이 답할",
    "지은의 메시지만",
    "메시지만 출력",
    "[analysis]",
    "[response]",
)


def _is_meta_line(line: str) -> bool:
    low = line.strip().lower()
    return any(ind in line or ind in low for ind in _META_INDICATORS)


def sanitize_response(text: str) -> str:
    """Strip leaked tokens, CJK, fullwidth punct, English runs, meta instructions,
    wrapping quotes, and speaker prefixes.

    Conservative w.r.t. normal Korean output.
    """
    text = _CHAT_TOKENS.sub("", text)
    text = _DIVIDER.sub("", text)
    text = _NON_KOREAN_CJK.sub("", text)
    text = _FULLWIDTH_PUNCT.sub("", text)
    text = _ASCII_RUN.sub("", text)
    text = replace_hoching(text)
    text = _MULTI_SPACE.sub(" ", text)

    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_meta_line(line):
            continue
        line = _strip_speaker_prefix(line)
        line = _strip_wrapping_quotes(line)
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


@dataclass
class ChatMessage:
    role: Role
    content: str


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Ollama unreachable or model not loaded after retries."""


class LLM:
    def __init__(
        self,
        host: str,
        model: str,
        aux_model: Optional[str] = None,
        keep_alive: str = "24h",
        request_timeout: float = 120.0,
    ):
        self.host = host
        self.model = model
        self.aux_model = aux_model or model
        self.keep_alive = keep_alive
        self._client = ollama.Client(host=host, timeout=request_timeout)

    def chat(
        self,
        system: str,
        messages: list[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.55,
        max_retries: int = 3,
        retry_wait_seconds: float = 30.0,
        sanitize: bool = True,
    ) -> str:
        """Send a chat request. Retries transient failures with backoff.

        Raises LLMUnavailable after retries exhausted.
        """
        payload = [{"role": "system", "content": system}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]
        chosen_model = model or self.model

        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = self._client.chat(
                    model=chosen_model,
                    messages=payload,
                    keep_alive=self.keep_alive,
                    options={"temperature": temperature},
                )
                content = resp["message"]["content"]
                if not isinstance(content, str):
                    raise LLMError(f"unexpected response shape: {resp!r}")
                content = content.strip()
                return sanitize_response(content) if sanitize else content
            except (httpx.HTTPError, ollama.ResponseError) as e:
                last_err = e
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s", attempt, max_retries, e
                )
                if attempt < max_retries:
                    time.sleep(retry_wait_seconds)
        raise LLMUnavailable(f"LLM chat failed after {max_retries} attempts: {last_err}") from last_err

    def quick(self, prompt: str, *, use_aux: bool = False, temperature: float = 0.3) -> str:
        """One-shot prompt; use_aux=True routes to the small auxiliary model.

        Useful for emotion scoring and summarization.
        """
        return self.chat(
            system="",
            messages=[ChatMessage(role="user", content=prompt)],
            model=self.aux_model if use_aux else self.model,
            temperature=temperature,
        )

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as c:
                r = c.get(f"{self.host}/api/version")
                return r.status_code == 200
        except httpx.HTTPError:
            return False
