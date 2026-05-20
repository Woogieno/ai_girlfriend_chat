"""AI Girlfriend Companion Bot — entry point.

Wires together: channel, agent (LLM + persona + triggers + responder), memory,
state store, and scheduler (proactive + idle + decay).

Main loop:
  - polls the channel every POLL_MIN..POLL_MAX seconds (jittered)
  - for each owner message: log → analyze triggers → update state → respond
  - the BackgroundScheduler concurrently fires proactive/idle/decay jobs

Halts cleanly on SIGINT/SIGTERM. Halts sends on ChannelChallenge.
"""
from __future__ import annotations

import logging
import random
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ai_gf.agent.llm import LLM
from ai_gf.agent.responder import Responder
from ai_gf.agent.triggers import analyze
from ai_gf.channel.base import ChannelChallenge, ChannelLoginError, InboundMessage
from ai_gf.channel.instagram import InstagramChannel
from ai_gf.config import Settings, load_settings
from ai_gf.memory.log import MemoryLog
from ai_gf.scheduler.proactive import ProactiveScheduler
from ai_gf.state.store import Store

log = logging.getLogger("ai_gf.app")


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Quiet down noisy libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("instagrapi").setLevel(logging.WARNING)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(
        RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=7, encoding="utf-8")
    )
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def handle_inbound(
    inbound: InboundMessage,
    store: Store,
    memory: MemoryLog,
    llm: LLM,
    responder: Responder,
) -> None:
    log.info(
        "Inbound: id=%s len=%d ts=%s",
        inbound.thread_id,
        len(inbound.body),
        inbound.ts.isoformat() if inbound.ts else "?",
    )

    # Log first so the message persists even if response fails mid-pipeline.
    memory.append("in", inbound.sender_ig_id, inbound.body)
    store.touch_last_user_msg()

    # Analyze for state changes (jealousy/affection/mood). Decay/summary handled
    # by the scheduler on a clock.
    state = store.get_state()
    analysis = analyze(inbound.body, state, llm=llm)
    if analysis.delta.reason != "no_trigger" or analysis.delta.affection or analysis.delta.jealousy:
        store.update_state(analysis.delta)
        state = store.get_state()
        log.info(
            "Triggers matched=%s delta=(a=%+d, j=%+d, mood=%s)",
            analysis.matched,
            analysis.delta.affection,
            analysis.delta.jealousy,
            analysis.delta.mood,
        )

    # Compose and send a reply. The responder enforces caps + jitter.
    sent = responder.respond_to(inbound, state)
    if sent is not None:
        log.info("Replied (len=%d)", len(sent))

    # Optionally trigger summarization after each turn — cheap check, only does
    # work when the unsummarized count crosses the threshold.
    if memory.should_summarize():
        log.info("Threshold crossed — generating summary...")
        memory.do_summarize()


def poll_loop(
    stop: threading.Event,
    settings: Settings,
    channel: InstagramChannel,
    store: Store,
    memory: MemoryLog,
    llm: LLM,
    responder: Responder,
) -> None:
    while not stop.is_set():
        try:
            inbox = channel.fetch_inbound()
        except ChannelChallenge as e:
            log.error("Channel challenge — halting bot: %s", e)
            stop.set()
            return
        except ChannelLoginError as e:
            log.error("Login error: %s — backing off 5min", e)
            stop.wait(timeout=300)
            continue
        except Exception:
            log.exception("Unexpected error in poll cycle")
            stop.wait(timeout=60)
            continue

        for msg in inbox:
            try:
                handle_inbound(msg, store, memory, llm, responder)
            except Exception:
                log.exception("Error handling inbound — moving on")

        # Jittered sleep before next poll.
        delay = random.uniform(settings.poll_min_seconds, settings.poll_max_seconds)
        stop.wait(timeout=delay)


def main() -> int:
    settings = load_settings()
    setup_logging(settings.log_path)

    log.info(
        "Starting ai_gf bot (model=%s, owner=%s, tz=%s)",
        settings.ollama_model,
        settings.owner_ig_user_id,
        settings.timezone,
    )

    # ----- components -----
    store = Store(settings.db_path)
    llm = LLM(
        host=settings.ollama_host,
        model=settings.ollama_model,
        aux_model=settings.ollama_aux_model,
    )
    if not llm.health_check():
        log.error("Ollama is not reachable at %s — aborting", settings.ollama_host)
        return 2

    memory = MemoryLog(store, llm)
    channel = InstagramChannel(
        username=settings.ig_username,
        password=settings.ig_password,
        owner_ig_user_id=settings.owner_ig_user_id,
        session_path=settings.ig_session_path,
    )
    try:
        channel.login()
    except ChannelChallenge as e:
        log.error("Login challenge — please resolve in Instagram app, then restart: %s", e)
        return 3
    except ChannelLoginError as e:
        log.error("Login failed: %s", e)
        return 3

    responder = Responder(
        store=store,
        memory=memory,
        llm=llm,
        channel=channel,
        owner_ig_id=settings.owner_ig_user_id,
        send_jitter_min_s=settings.send_jitter_min_seconds,
        send_jitter_max_s=settings.send_jitter_max_seconds,
        daily_proactive_cap=settings.daily_proactive_cap,
        daily_response_cap=settings.daily_response_cap,
    )

    scheduler = ProactiveScheduler(
        store=store,
        responder=responder,
        timezone_name=settings.timezone,
        idle_detection_hours=settings.idle_detection_hours,
    )
    scheduler.start()

    # ----- shutdown -----
    stop = threading.Event()

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("Signal %d received, shutting down.", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # ----- run -----
    log.info("All components ready. Entering poll loop.")
    try:
        poll_loop(stop, settings, channel, store, memory, llm, responder)
    finally:
        scheduler.stop()
        log.info("Goodbye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
