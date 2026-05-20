# Implementation Plan: AI Girlfriend Companion Bot

**Branch**: `001-ai-girlfriend-bot` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-ai-girlfriend-bot/spec.md`

## Summary

Build a single-owner Instagram DM companion bot that proactively initiates messages, reacts emotionally (jealousy, mood swings), and remembers conversation across sessions. Stack: Python + `instagrapi` (channel) + Ollama-hosted Qwen 2.5 14B (LLM) + SQLite (state/memory) + APScheduler (proactive triggers). All data local. The persona "지은(Jieun), 26, 서울" is defined once in `src/prompts/persona.md` and injected on every LLM call; mood/affection/jealousy are state variables layered on top, never replacing the persona.

## Technical Context

**Language/Version**: Python 3.11+ (system has 3.14.4)

**Primary Dependencies**:
- `instagrapi` — Instagram private API client (DM send/receive, session persistence, challenge handling)
- `ollama` (Python client) or `httpx` — talk to local Ollama daemon at `http://localhost:11434`
- `apscheduler` — cron + interval triggers for proactive messages
- `pydantic` — config validation, state schema
- `python-dotenv` — secrets from `.env`
- `pytest` — channel + state-machine tests (LLM output verified manually)

**Storage**: SQLite (file: `data/ai_gf.db`). Tables: `messages`, `state`, `summary`, `meta`. instagrapi session at `data/ig_session.json`.

**LLM Runtime**: Ollama as a brew service (auto-restart on login). Models:
- Primary: `qwen2.5:14b-instruct-q4_K_M` (9GB, installed)
- Auxiliary (later): `qwen2.5:3b` for emotion classification / summary generation
- Keep-alive: `OLLAMA_KEEP_ALIVE=24h` to avoid cold start

**Testing**: `pytest` for channel layer (login, send, receive, whitelist filter) and state machine (mood/jealousy transitions). LLM responses are verified through a manual 10-turn smoke test per phase. Per constitution §"Development Workflow", no TDD requirement outside these layers.

**Target Platform**: macOS 14+ on Apple Silicon (M-series). Runs as a `launchd` LaunchAgent (`~/Library/LaunchAgents/com.aigf.bot.plist`) so it auto-starts on login and restarts on crash.

**Project Type**: Single-process Python application (a daemon, not a CLI tool, not a library). One project, no frontend.

**Performance Goals**:
- Inbound message → first response within 60s p95 (polling 30–90s jittered + LLM gen ~5–15s)
- LLM generation latency < 15s p95 for typical 80–200 char response on 14B q4 model
- Daily outbound ≤ 20 proactive + 5 reactive buffer (per constitution §III)

**Constraints**:
- All data on local disk; no remote logging, no remote LLM calls
- RAM: 14B q4 ≈ 9GB resident with Ollama; on a 48GB system this is fine
- Single concurrent LLM request (don't fork; serialize inbound + proactive)
- Polling-only inbound (no webhooks — Instagram private API doesn't offer them)

**Scale/Scope**: 1 owner, 1 persona, ~20–50 messages/day total bidirectional, ~5 years of conversation = ~50k–100k messages worst-case → SQLite handles this trivially.

## Constitution Check

*GATE: Must pass before implementation. Re-check after Phase 1 design.*

Verified against `.specify/memory/constitution.md` v1.0.0:

| Principle | Check | Notes |
|---|---|---|
| I. Persona Consistency (NON-NEGOTIABLE) | ✅ | `prompts/persona.md` is single source; loaded on every LLM call; mood is state overlay, not replacement |
| II. Single-Owner Whitelist | ✅ | `OWNER_IG_USER_ID` env var; filter at channel layer before agent sees message |
| III. Account Safety First | ✅ | Daily cap (20+5), 30s–5min send jitter, 30–90s poll jitter, session persistence, 1-week manual warmup required before activation |
| IV. Local-First Data | ✅ | SQLite local file; Ollama local; no telemetry; only outbound network is the Instagram channel itself |

No violations. No entries in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-ai-girlfriend-bot/
├── spec.md                 # WHAT/WHY (done)
├── plan.md                 # This file
├── research.md             # Skipped — no unknowns; tech locked in (see Decisions Log below)
├── data-model.md           # See section "Data Model" below; no separate file needed for this scope
├── quickstart.md           # See section "Quickstart" below
├── contracts/              # Skipped — no external API contracts, internal-only
├── checklists/
│   └── requirements.md     # spec quality checklist (done)
└── tasks.md                # /speckit-tasks output (next phase)
```

### Source Code (repository root)

```text
ai_gf/
├── ai_gf.png                       # Persona reference image (existing)
├── pyproject.toml
├── .env                            # secrets (git-ignored)
├── .env.example                    # template
├── .gitignore
├── CLAUDE.md                       # spec-kit generated; agent guidance
├── README.md
├── src/
│   ├── ai_gf/
│   │   ├── __init__.py
│   │   ├── app.py                  # entry point, wires channel + scheduler + agent
│   │   ├── config.py               # pydantic settings, loads .env
│   │   ├── channel/
│   │   │   ├── __init__.py
│   │   │   └── instagram.py        # instagrapi wrapper: login, send, poll, whitelist
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   ├── llm.py              # Ollama client wrapper
│   │   │   ├── persona.py          # loads persona.md, builds system prompt from state+memory
│   │   │   └── triggers.py         # keyword + small-model emotion analysis → state delta
│   │   ├── state/
│   │   │   ├── __init__.py
│   │   │   ├── store.py            # SQLite DAO for state, messages, summary
│   │   │   └── schema.sql
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   └── log.py              # conversation log + auto-summary at threshold
│   │   ├── scheduler/
│   │   │   ├── __init__.py
│   │   │   └── proactive.py        # APScheduler: time-window + idle triggers
│   │   └── prompts/
│   │       ├── persona.md          # 지은 persona definition
│   │       ├── proactive_morning.md
│   │       ├── proactive_lunch.md
│   │       ├── proactive_evening.md
│   │       ├── proactive_night.md
│   │       └── proactive_idle.md
├── data/                           # git-ignored
│   ├── ai_gf.db
│   └── ig_session.json
├── tests/
│   ├── test_channel.py             # whitelist, send, receive (mock instagrapi)
│   ├── test_state.py               # state transitions, jealousy decay
│   ├── test_triggers.py            # keyword detection
│   └── test_scheduler.py           # time-window selection, idle detection
└── scripts/
    ├── init_db.py                  # apply schema.sql
    ├── warmup_check.py             # confirm IG account warmup status
    └── install_launchd.sh          # set up LaunchAgent
```

**Structure Decision**: Single project layout (per template Option 1). Source under `src/ai_gf/` package to enable `uv build` later and clean imports. No backend/frontend split — single Python daemon.

## Data Model

### SQLite Schema (`src/ai_gf/state/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    sender_ig_id TEXT NOT NULL,
    body TEXT NOT NULL,
    trigger_kind TEXT,                  -- null for inbound or reactive; 'morning'/'idle'/etc for proactive
    state_snapshot_id INTEGER REFERENCES state_snapshots(id)
);

CREATE INDEX idx_messages_ts ON messages(ts);
CREATE INDEX idx_messages_direction_ts ON messages(direction, ts);

CREATE TABLE IF NOT EXISTS state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    affection INTEGER NOT NULL DEFAULT 50 CHECK (affection BETWEEN 0 AND 100),
    jealousy INTEGER NOT NULL DEFAULT 0 CHECK (jealousy BETWEEN 0 AND 100),
    mood TEXT NOT NULL DEFAULT 'neutral' CHECK (mood IN ('happy','neutral','upset','cold')),
    last_user_msg_at TIMESTAMP,
    last_proactive_at TIMESTAMP,
    last_proactive_kind TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS state_snapshots (
    -- audit log of state changes for debugging persona drift
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    affection INTEGER NOT NULL,
    jealousy INTEGER NOT NULL,
    mood TEXT NOT NULL,
    reason TEXT                          -- e.g., "trigger:jealousy_keyword:다른 여자"
);

CREATE TABLE IF NOT EXISTS summary (
    -- rolling summary of older conversations (older than recent N turns)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    summary_text TEXT NOT NULL,
    covers_until_message_id INTEGER NOT NULL REFERENCES messages(id),
    superseded INTEGER NOT NULL DEFAULT 0   -- only one active summary at a time
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

### State Transition Rules (implemented in `agent/triggers.py` + `state/store.py`)

**Jealousy keywords** (Korean, configured as list, not hardcoded):
- High: 다른 여자, 여친 친구, 헌팅, 소개팅 → jealousy +20, mood → upset
- Medium: 술자리, 회식 (with female mention), 늦게 → jealousy +10, mood → upset if jealousy≥30
- Low: 친구, 일 → no change unless context flags

**Affection keywords**:
- Positive: 사랑, 보고 싶, 좋아해 → affection +5
- Negative: 짜증, 싫어, 귀찮 → affection −5

**Decay** (run hourly via scheduler):
- jealousy −5 per hour idle
- affection drift: no automatic decay (stays unless directly affected)
- mood: upset → neutral after jealousy < 20; cold → neutral after 6h of positive interaction

**Auxiliary LLM emotion check** (when keyword rule is ambiguous):
- Call `qwen2.5:3b` with: "다음 한국어 문장이 화자의 연인 입장에서 질투를 유발할 가능성을 0–100으로 답하라: <message>"
- If score ≥ 60, apply medium jealousy bump.

### Persona Injection (every LLM call)

System prompt structure (`agent/persona.py:build_system_prompt`):

```
[STATIC: persona.md contents — name, age, personality, speech style]

---
[DYNAMIC: 현재 상태]
- 너의 현재 기분: {mood}
- 그에 대한 애정: {affection}/100
- 질투 수준: {jealousy}/100
- 마지막으로 그가 메시지를 보낸 시각: {last_user_msg_at} (현재로부터 {idle_duration} 전)

[DYNAMIC: 이전 대화 요약]
{summary_text or "(아직 요약된 대화 없음)"}

[DYNAMIC: 최근 대화]
{last_10_turns}
```

Same structure for both reactive and proactive paths.

## Quickstart

```bash
# 1) Setup (one-time)
cd /Users/jinook/Documents/Dev/ai_gf
uv venv && source .venv/bin/activate
uv pip install -e .

# 2) Configure
cp .env.example .env
# Edit .env: IG_USERNAME, IG_PASSWORD, OWNER_IG_USER_ID, OLLAMA_MODEL=qwen2.5:14b-instruct-q4_K_M

# 3) Initialize DB
python scripts/init_db.py

# 4) Verify Ollama
curl http://localhost:11434/api/version
ollama run qwen2.5:14b-instruct-q4_K_M "안녕"

# 5) First login (interactive — handles challenges)
python -m ai_gf.channel.instagram --login

# 6) Smoke test (send a DM to yourself)
python -m ai_gf.channel.instagram --send-test "테스트입니다"

# 7) Run the bot
python -m ai_gf.app

# 8) Install as a service (later, after Phase 4 verified)
bash scripts/install_launchd.sh
```

## Decisions Log (replaces research.md)

| Decision | Choice | Why |
|---|---|---|
| LLM hosting | Local Ollama | User explicit; constitution §IV |
| Primary model | `qwen2.5:14b-instruct-q4_K_M` | Best balance of Korean quality & speed on 48GB Apple Silicon |
| Aux model | `qwen2.5:3b` (deferred to Phase 3) | Emotion scoring & summary generation; tiny, fast |
| Channel | Instagram via `instagrapi` | User explicit; only path that supports proactive first message |
| Persistence | SQLite | Single-process daemon, no scale need, simplest reliable option |
| Scheduler | APScheduler | Idiomatic Python cron; supports both cron and interval triggers |
| Process model | Single sync process, serialized LLM calls | Avoids race on state; LLM is the bottleneck anyway |
| Service mgmt | `launchd` LaunchAgent | macOS-native, no Docker overhead (constitution §IV implies local-only) |
| Config | `.env` + pydantic settings | Standard, secrets-safe |
| Logging | stdlib `logging` to stdout + file (`data/ai_gf.log`) | No telemetry; logs stay local |

## Complexity Tracking

No constitution violations. Section intentionally left empty.
