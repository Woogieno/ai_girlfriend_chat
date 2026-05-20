from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class InboundMessage:
    """A message received from the channel.

    Only messages from the owner reach this layer — non-owner messages are
    dropped at the channel implementation per constitution §II.
    """
    sender_ig_id: str
    body: str
    ts: datetime
    thread_id: str | None = None


class ChannelLoginError(RuntimeError):
    """Login failed (bad credentials, or session invalidated)."""


class ChannelChallenge(RuntimeError):
    """Instagram demanded a challenge (2FA/SMS/email). Operator action required.

    Per constitution §III and spec edge case, the bot MUST halt sends when
    raised and surface this to the operator.
    """


@runtime_checkable
class Channel(Protocol):
    """The minimal interface the app layer depends on. Channel implementations
    are responsible for:
      - authenticating and persisting sessions
      - applying the single-owner whitelist BEFORE returning inbound messages
      - sending outbound text
      - halting (raising ChannelChallenge) when Instagram demands a challenge
    """

    def login(self) -> None: ...

    def fetch_inbound(self) -> list[InboundMessage]:
        """Return only owner-authored messages received since the last fetch.

        Non-owner messages are dropped here. Metadata about dropped messages
        MAY be logged but their body MUST NOT be stored.
        """
        ...

    def send(self, text: str) -> None: ...
