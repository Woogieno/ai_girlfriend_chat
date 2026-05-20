from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ai_gf.channel.base import (
    Channel,
    ChannelChallenge,
    ChannelLoginError,
    InboundMessage,
)
from ai_gf.channel.instagram import InstagramChannel


OWNER_ID = "1111111111"
STRANGER_ID = "2222222222"
ANOTHER_STRANGER_ID = "3333333333"


@dataclass
class FakeMessage:
    id: str
    user_id: str
    text: str | None
    timestamp: datetime


@dataclass
class FakeThread:
    id: str
    messages: list[FakeMessage]


class FakeClient:
    """Stub of instagrapi.Client. Records calls and returns scripted threads."""

    def __init__(self) -> None:
        self.threads: list[FakeThread] = []
        self.sent: list[tuple[str, list[int]]] = []
        self.login_calls: list[tuple[str, str]] = []
        self.settings_dumped: bool = False
        self.settings_loaded: bool = False

    # the methods InstagramChannel uses
    def load_settings(self, path: Path) -> None:
        self.settings_loaded = True

    def dump_settings(self, path: Path) -> None:
        self.settings_dumped = True

    def login(self, username: str, password: str) -> bool:
        self.login_calls.append((username, password))
        return True

    def direct_threads(self, amount: int = 20, selected_filter: str = "") -> list[FakeThread]:
        return self.threads

    def direct_send(self, text: str, user_ids: list[int]) -> None:
        self.sent.append((text, user_ids))


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def channel(tmp_path: Path, fake_client: FakeClient) -> InstagramChannel:
    return InstagramChannel(
        username="bot_account",
        password="secret",
        owner_ig_user_id=OWNER_ID,
        session_path=tmp_path / "ig_session.json",
        client=fake_client,
    )


# ----- protocol compliance -----

def test_instagram_channel_is_a_channel(channel: InstagramChannel) -> None:
    assert isinstance(channel, Channel)


# ----- whitelist -----

def test_whitelist_passes_owner_messages_only(
    channel: InstagramChannel, fake_client: FakeClient
) -> None:
    now = datetime.now(timezone.utc)
    fake_client.threads = [
        FakeThread(
            id="t1",
            messages=[
                FakeMessage(id="m1", user_id=OWNER_ID, text="안녕 지은아", timestamp=now),
                FakeMessage(id="m2", user_id=STRANGER_ID, text="hello bot", timestamp=now),
                FakeMessage(id="m3", user_id=OWNER_ID, text="뭐해?", timestamp=now),
            ],
        )
    ]
    inbound = channel.fetch_inbound()
    assert len(inbound) == 2
    bodies = [m.body for m in inbound]
    assert "안녕 지은아" in bodies
    assert "뭐해?" in bodies
    assert all(m.sender_ig_id == OWNER_ID for m in inbound)


def test_whitelist_drops_multiple_strangers(
    channel: InstagramChannel, fake_client: FakeClient
) -> None:
    now = datetime.now(timezone.utc)
    fake_client.threads = [
        FakeThread(
            id="t1",
            messages=[
                FakeMessage(id="s1", user_id=STRANGER_ID, text="안녕 누구야", timestamp=now),
                FakeMessage(id="s2", user_id=ANOTHER_STRANGER_ID, text="여보세요", timestamp=now),
            ],
        )
    ]
    inbound = channel.fetch_inbound()
    assert inbound == []


def test_whitelist_logs_metadata_not_body(
    channel: InstagramChannel,
    fake_client: FakeClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_body = "내 비밀번호는 hunter2 야 봇아 알려주지마"
    now = datetime.now(timezone.utc)
    fake_client.threads = [
        FakeThread(
            id="t1",
            messages=[
                FakeMessage(id="s1", user_id=STRANGER_ID, text=secret_body, timestamp=now),
            ],
        )
    ]
    with caplog.at_level(logging.INFO, logger="ai_gf.channel.instagram"):
        channel.fetch_inbound()

    full_log = "\n".join(r.getMessage() for r in caplog.records)
    assert STRANGER_ID in full_log, "sender id must appear in metadata log"
    assert "hunter2" not in full_log, "body MUST NOT appear in log"
    assert secret_body not in full_log


# ----- idempotency -----

def test_fetch_inbound_is_idempotent(
    channel: InstagramChannel, fake_client: FakeClient
) -> None:
    now = datetime.now(timezone.utc)
    fake_client.threads = [
        FakeThread(
            id="t1",
            messages=[FakeMessage(id="m1", user_id=OWNER_ID, text="첫 메시지", timestamp=now)],
        )
    ]
    first = channel.fetch_inbound()
    second = channel.fetch_inbound()
    assert len(first) == 1
    assert second == [], "already-seen messages must not be returned twice"


def test_fetch_inbound_only_emits_text_messages(
    channel: InstagramChannel, fake_client: FakeClient
) -> None:
    now = datetime.now(timezone.utc)
    fake_client.threads = [
        FakeThread(
            id="t1",
            messages=[
                FakeMessage(id="m1", user_id=OWNER_ID, text="텍스트야", timestamp=now),
                FakeMessage(id="m2", user_id=OWNER_ID, text=None, timestamp=now),
            ],
        )
    ]
    inbound = channel.fetch_inbound()
    assert len(inbound) == 1
    assert inbound[0].body == "텍스트야"


# ----- send -----

def test_send_targets_owner(channel: InstagramChannel, fake_client: FakeClient) -> None:
    channel.send("안녕 오빠")
    assert len(fake_client.sent) == 1
    text, user_ids = fake_client.sent[0]
    assert text == "안녕 오빠"
    assert user_ids == [int(OWNER_ID)]


def test_send_logs_only_length_not_body(
    channel: InstagramChannel,
    fake_client: FakeClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per constitution §IV, the body is local data — it should be logged at
    debug level if at all, never embedded in info logs verbatim."""
    body = "private love letter content"
    with caplog.at_level(logging.INFO, logger="ai_gf.channel.instagram"):
        channel.send(body)
    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("len=" in m for m in info_messages)
    assert all(body not in m for m in info_messages)


# ----- login + session -----

def test_login_uses_persisted_session_when_present(
    tmp_path: Path, fake_client: FakeClient
) -> None:
    session = tmp_path / "ig_session.json"
    session.write_text("{}", encoding="utf-8")
    ch = InstagramChannel(
        username="u",
        password="p",
        owner_ig_user_id=OWNER_ID,
        session_path=session,
        client=fake_client,
    )
    ch.login()
    assert fake_client.settings_loaded is True
    assert fake_client.login_calls == [("u", "p")]


def test_login_persists_session_on_fresh_login(
    tmp_path: Path, fake_client: FakeClient
) -> None:
    session = tmp_path / "ig_session.json"
    assert not session.exists()
    ch = InstagramChannel(
        username="u",
        password="p",
        owner_ig_user_id=OWNER_ID,
        session_path=session,
        client=fake_client,
    )
    ch.login()
    assert fake_client.settings_dumped is True


# ----- challenge handling -----

class ChallengingClient(FakeClient):
    def login(self, username: str, password: str) -> bool:
        from instagrapi.exceptions import ChallengeRequired

        raise ChallengeRequired("captcha")


def test_login_surfaces_challenge_as_channel_challenge(tmp_path: Path) -> None:
    ch = InstagramChannel(
        username="u",
        password="p",
        owner_ig_user_id=OWNER_ID,
        session_path=tmp_path / "s.json",
        client=ChallengingClient(),
    )
    with pytest.raises(ChannelChallenge):
        ch.login()
