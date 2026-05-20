from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    LoginRequired,
    TwoFactorRequired,
)

from .base import (
    Channel,
    ChannelChallenge,
    ChannelLoginError,
    InboundMessage,
)

logger = logging.getLogger(__name__)


class InstagramChannel(Channel):
    """instagrapi-backed channel with single-owner whitelist enforced at the
    fetch_inbound boundary.
    """

    def __init__(
        self,
        username: str,
        password: str,
        owner_ig_user_id: str,
        session_path: Path,
        *,
        client: Optional[Client] = None,
    ):
        self.username = username
        self.password = password
        self.owner_ig_user_id = str(owner_ig_user_id)
        self.session_path = Path(session_path)
        self.client = client or Client()
        self._logged_in = False
        # Track which DM ids we've already returned, so fetch_inbound
        # is idempotent and doesn't re-emit the same message.
        self._seen_message_ids: set[str] = set()
        self._last_seen_meta_path = self.session_path.parent / "ig_seen_messages.json"
        self._load_seen()

    # ----- session persistence -----

    def _load_seen(self) -> None:
        if self._last_seen_meta_path.exists():
            try:
                data = json.loads(self._last_seen_meta_path.read_text(encoding="utf-8"))
                self._seen_message_ids = set(data.get("seen", []))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load seen-messages cache: %s", e)
                self._seen_message_ids = set()

    def _save_seen(self) -> None:
        # Keep only the most recent 10k IDs to bound disk usage.
        recent = list(self._seen_message_ids)[-10_000:]
        self._last_seen_meta_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_seen_meta_path.write_text(
            json.dumps({"seen": recent}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._seen_message_ids = set(recent)

    # ----- channel API -----

    def login(self) -> None:
        if self._logged_in:
            return
        if self.session_path.exists():
            try:
                self.client.load_settings(self.session_path)
                self.client.login(self.username, self.password)
                self._logged_in = True
                logger.info("Logged in via persisted session.")
                return
            except (LoginRequired, BadPassword) as e:
                logger.warning("Persisted session unusable (%s); re-authenticating.", e)
        try:
            self.client.login(self.username, self.password)
        except ChallengeRequired as e:
            raise ChannelChallenge(f"Instagram challenge required: {e}") from e
        except TwoFactorRequired as e:
            raise ChannelChallenge(f"2FA required: {e}") from e
        except BadPassword as e:
            raise ChannelLoginError(f"Bad password: {e}") from e

        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.dump_settings(self.session_path)
        self._logged_in = True
        logger.info("Logged in fresh and saved session.")

    def fetch_inbound(self) -> list[InboundMessage]:
        if not self._logged_in:
            self.login()

        try:
            threads = self.client.direct_threads(amount=20, selected_filter="unread")
        except ChallengeRequired as e:
            raise ChannelChallenge(f"Challenge mid-fetch: {e}") from e
        except LoginRequired as e:
            self._logged_in = False
            raise ChannelLoginError(f"Session invalidated: {e}") from e

        out: list[InboundMessage] = []
        dropped_non_owner = 0
        for thread in threads:
            for msg in thread.messages or []:
                msg_id = getattr(msg, "id", None)
                if msg_id is None:
                    continue
                msg_id = str(msg_id)
                if msg_id in self._seen_message_ids:
                    continue
                self._seen_message_ids.add(msg_id)

                sender_id = str(getattr(msg, "user_id", "") or "")
                if not sender_id or sender_id == self.username:
                    # Outbound echo or unknown sender — skip silently.
                    continue
                if sender_id != self.owner_ig_user_id:
                    dropped_non_owner += 1
                    logger.info(
                        "Dropped non-owner message: sender_id=%s ts=%s (body NOT stored)",
                        sender_id,
                        getattr(msg, "timestamp", None),
                    )
                    continue

                body = getattr(msg, "text", None)
                if not body:
                    # Non-text message (image, reaction, etc.) — v1 ignores
                    continue

                ts = getattr(msg, "timestamp", None) or datetime.now(timezone.utc)
                out.append(
                    InboundMessage(
                        sender_ig_id=sender_id,
                        body=body,
                        ts=ts,
                        thread_id=getattr(thread, "id", None),
                    )
                )

        if dropped_non_owner:
            logger.warning("Dropped %d non-owner messages this poll cycle.", dropped_non_owner)

        self._save_seen()
        # instagrapi returns newest-first; preserve chronological order downstream.
        return list(reversed(out))

    def send(self, text: str) -> None:
        if not self._logged_in:
            self.login()
        try:
            self.client.direct_send(text, user_ids=[int(self.owner_ig_user_id)])
            logger.info("Sent message to owner (len=%d)", len(text))
        except ChallengeRequired as e:
            raise ChannelChallenge(f"Challenge mid-send: {e}") from e
        except LoginRequired as e:
            self._logged_in = False
            raise ChannelLoginError(f"Session invalidated during send: {e}") from e
