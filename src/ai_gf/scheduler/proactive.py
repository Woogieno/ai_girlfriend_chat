"""APScheduler wiring for proactive messaging + hourly decay + idle detection.

Time windows (Asia/Seoul, from spec.md):
  - morning  08:00–10:00
  - lunch    12:00–13:30
  - evening  18:00–20:00
  - night    22:00–23:30

Each window fires once at a jittered minute inside the window. We accomplish
this by scheduling one CronTrigger at the *start* of each window and inside
the job picking a delayed run via threading.Timer.

Idle detection runs every 30 minutes and decides whether to send an 'idle'
proactive based on time since the owner's last message.

Hourly decay runs every hour and softens jealousy.
"""
from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ai_gf.agent.responder import Responder
from ai_gf.agent.triggers import hourly_decay
from ai_gf.state.store import Store, StateDelta

logger = logging.getLogger(__name__)


# (kind, start_hour, start_min, window_minutes)
WINDOWS: list[tuple[str, int, int, int]] = [
    ("morning", 8, 0, 120),    # 08:00 – 10:00
    ("lunch", 12, 0, 90),       # 12:00 – 13:30
    ("evening", 18, 0, 120),    # 18:00 – 20:00
    ("night", 22, 0, 90),       # 22:00 – 23:30
]


def current_window(now: datetime, windows: list[tuple[str, int, int, int]] = WINDOWS) -> Optional[str]:
    """Return the kind of window `now` falls inside, or None."""
    for kind, h, m, dur in windows:
        start_minutes = h * 60 + m
        now_minutes = now.hour * 60 + now.minute
        if start_minutes <= now_minutes < start_minutes + dur:
            return kind
    return None


class ProactiveScheduler:
    def __init__(
        self,
        store: Store,
        responder: Responder,
        timezone_name: str = "Asia/Seoul",
        idle_detection_hours: int = 4,
    ):
        self.store = store
        self.responder = responder
        self.tz = ZoneInfo(timezone_name)
        self.idle_detection_hours = idle_detection_hours
        self.scheduler = BackgroundScheduler(timezone=self.tz)
        self._timers: list[threading.Timer] = []

    # ----- public lifecycle -----

    def start(self) -> None:
        for kind, h, m, dur in WINDOWS:
            self.scheduler.add_job(
                self._schedule_window_send,
                trigger=CronTrigger(hour=h, minute=m, timezone=self.tz),
                args=[kind, dur],
                id=f"window_{kind}",
                replace_existing=True,
            )

        # Keep-alive + window catch-up + idle catch-up — all in one tick.
        # Short interval (5 min) so we recover quickly from macOS sleep.
        self.scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(minutes=5),
            id="proactive_tick",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self._apply_decay,
            trigger=IntervalTrigger(hours=1),
            id="hourly_decay",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            "Scheduler started. Windows: %s, idle threshold: %dh",
            [w[0] for w in WINDOWS],
            self.idle_detection_hours,
        )

        # Catch-up: if the bot starts (or wakes from sleep) inside an active
        # window and hasn't sent today, fire it now with a short jitter.
        self._catchup_current_window()

    def stop(self) -> None:
        for t in self._timers:
            t.cancel()
        self._timers.clear()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    # ----- jobs -----

    def _schedule_window_send(self, kind: str, window_minutes: int) -> None:
        """Pick a random minute inside the window and arm a Timer to fire then.

        Skip if today's same window already sent.
        """
        if self._already_sent_today(kind):
            logger.info("Skipping %s — already sent today", kind)
            return
        delay_seconds = random.uniform(0, window_minutes * 60)
        t = threading.Timer(delay_seconds, self._do_window_send, args=[kind])
        t.daemon = True
        t.start()
        self._timers.append(t)
        logger.info("Armed %s to fire in %.0fs", kind, delay_seconds)

    def _do_window_send(self, kind: str) -> None:
        if self._already_sent_today(kind):
            return
        try:
            state = self.store.get_state()
            self.responder.send_proactive(kind, state)
        except Exception as e:
            logger.exception("Proactive %s send failed: %s", kind, e)

    def _check_idle(self) -> None:
        state = self.store.get_state()
        last = state.last_user_msg_at
        if last is None:
            return
        elapsed = datetime.now(timezone.utc) - last
        if elapsed < timedelta(hours=self.idle_detection_hours):
            return
        # Avoid re-firing idle within the same gap. Re-fire only if 2h passed
        # since the last *proactive of any kind* — same gating used for windows.
        if state.last_proactive_at:
            since_last_prx = datetime.now(timezone.utc) - state.last_proactive_at
            if since_last_prx < timedelta(hours=2):
                return
        try:
            self.responder.send_proactive("idle", state)
        except Exception as e:
            logger.exception("Idle send failed: %s", e)

    def _catchup_current_window(self) -> None:
        """If we're inside an active window and haven't sent today, fire soon.

        Handles two cases:
          1. Bot starts late in a window (e.g., after a system sleep that
             swallowed the 08:00 cron).
          2. Manual restart inside a window.
        """
        now = datetime.now(self.tz)
        kind = current_window(now)
        if not kind:
            return
        if self._already_sent_today(kind):
            return
        delay = random.uniform(10, 60)
        t = threading.Timer(delay, self._do_window_send, args=[kind])
        t.daemon = True
        t.start()
        self._timers.append(t)
        logger.info("Catch-up: armed %s to fire in %.0fs (window is active)", kind, delay)

    def _tick(self) -> None:
        """Single 5-minute heartbeat: keep LLM warm, catch up any missed
        window proactive, catch up missed idle send.

        Every concern wrapped in its own try/except — they're independent.
        Running on a short interval means macOS sleep windows are detected
        within ~5 minutes of wakeup at worst.
        """
        try:
            self.responder.llm.quick("응", temperature=0.0)
        except Exception as e:
            logger.warning("LLM keepalive ping failed: %s", e)
        try:
            self._catchup_current_window()
        except Exception as e:
            logger.warning("window catch-up failed: %s", e)
        try:
            self._check_idle()
        except Exception as e:
            logger.warning("idle check failed: %s", e)

    def _apply_decay(self) -> None:
        state = self.store.get_state()
        delta = hourly_decay(state)
        if delta.jealousy == 0 and delta.affection == 0 and delta.mood is None:
            return
        self.store.update_state(delta)
        logger.info("Applied hourly decay: %s", delta)

    # ----- helpers -----

    def _already_sent_today(self, kind: str) -> bool:
        """True if we've sent a proactive of this kind today (local tz)."""
        import sqlite3
        with sqlite3.connect(self.store.db_path) as c:
            row = c.execute(
                "SELECT COUNT(*) FROM messages "
                "WHERE direction = 'out' AND trigger_kind = ? "
                "AND DATE(ts, 'localtime') = DATE('now', 'localtime')",
                (kind,),
            ).fetchone()
        return int(row[0]) > 0
