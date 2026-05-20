# Tasks: AI Girlfriend Companion Bot

**Input**: Design documents from `/specs/001-ai-girlfriend-bot/`

**Prerequisites**: spec.md, plan.md (both complete)

**Tests**: Channel and state-machine layers get pytest coverage per constitution §"Development Workflow". LLM output verified manually. No TDD.

**Organization**: Tasks grouped by user story. P1 stories (US1, US2, US5) form the MVP; P2 stories (US3, US4) ship after.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- File paths are absolute relative to repo root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, dependencies, secrets, DB.

- [ ] **T001** Initialize Python project: `pyproject.toml` with `instagrapi`, `ollama`, `apscheduler`, `pydantic`, `pydantic-settings`, `python-dotenv`, `pytest`. Use `uv venv && uv pip install -e .`
- [ ] **T002** [P] Create source tree: `src/ai_gf/{channel,agent,state,memory,scheduler,prompts}/__init__.py`, `tests/`, `scripts/`, `data/`
- [ ] **T003** [P] Write `.env.example` with `IG_USERNAME`, `IG_PASSWORD`, `OWNER_IG_USER_ID`, `OLLAMA_HOST=http://localhost:11434`, `OLLAMA_MODEL=qwen2.5:14b-instruct-q4_K_M`, `OLLAMA_AUX_MODEL=qwen2.5:3b`, `TIMEZONE=Asia/Seoul`, `DAILY_PROACTIVE_CAP=20`, `DAILY_RESPONSE_CAP=25`
- [ ] **T004** [P] Write `.gitignore`: `.env`, `data/`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`
- [ ] **T005** [P] Implement `src/ai_gf/config.py` — pydantic Settings class loading `.env`
- [ ] **T006** [P] Set `OLLAMA_KEEP_ALIVE=24h` via `launchctl setenv` (or document in README)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure shared by every user story.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [ ] **T010** Write `src/ai_gf/state/schema.sql` per plan.md "Data Model" section
- [ ] **T011** Implement `scripts/init_db.py` — applies schema.sql, idempotent
- [ ] **T012** [P] Implement `src/ai_gf/state/store.py` — DAO with `get_state()`, `update_state(delta, reason)`, `record_message(direction, body, ...)`, `recent_messages(limit)`, `active_summary()`, `set_summary()`
- [ ] **T013** [P] Write `tests/test_state.py` — DB CRUD, mood transitions, jealousy bounds (0–100), singleton state row enforcement
- [ ] **T014** Implement `src/ai_gf/agent/llm.py` — Ollama HTTP wrapper: `chat(system, messages, model=primary, timeout=60)`, retry-on-503 with backoff (max 3 tries, 5min wait per constitution edge case)
- [ ] **T015** [P] Smoke test: `python -c "from ai_gf.agent.llm import chat; print(chat('너는 친절한 한국어 화자야', [{'role':'user','content':'안녕'}]))"` should return Korean text
- [ ] **T016** Implement `src/ai_gf/agent/persona.py` — `load_persona()` reads `prompts/persona.md`; `build_system_prompt(state, summary, recent_turns)` composes per plan.md persona injection structure
- [ ] **T017** Implement `src/ai_gf/memory/log.py` — `append(direction, body)`, `recent_turns(n=10)`, `should_summarize()` (true when >50 unsummarized turns), `do_summarize()` (calls aux LLM, writes new summary, marks old superseded)
- [ ] **T018** Implement `src/ai_gf/app.py` skeleton — main entry, signal handling, logging setup (stdout + `data/ai_gf.log`), no behavior yet

**Checkpoint**: `pytest tests/test_state.py` passes. `ai-gf` package importable.

---

## Phase 3: User Story 5 - Single-Owner Whitelist (Priority: P1) 🎯 MVP Gate

**Goal**: Bot ignores non-owner DMs at the channel layer before any processing.

**Independent Test**: Send DM from a second Instagram account; verify zero processing, zero response, only metadata logged.

> Reordered to first because it's a safety prerequisite for all other stories.

### Implementation

- [ ] **T020** [US5] Implement `src/ai_gf/channel/instagram.py` core: `login()` (uses `data/ig_session.json`, falls back to credentials), `_save_session()`, `direct_threads_unread()` poller
- [ ] **T021** [US5] Implement whitelist filter: any inbound message where sender_id != `OWNER_IG_USER_ID` is dropped at `_process_inbound()` boundary; only metadata (timestamp + sender_id, NO body) goes to logger
- [ ] **T022** [P] [US5] Write `tests/test_channel.py::test_whitelist_drops_non_owner` — mock instagrapi, feed two messages (owner + stranger), assert only owner reaches downstream
- [ ] **T023** [P] [US5] Write `tests/test_channel.py::test_whitelist_logs_metadata_only` — assert stranger body never appears in log output

**Checkpoint**: US5 acceptance scenarios 1–3 all pass. Safe to add owner-facing logic.

---

## Phase 4: User Story 2 - Jealousy and Mood Reactions (Priority: P1)

**Goal**: Owner says jealousy-trigger phrases → bot reacts emotionally → mood persists across turns.

**Independent Test**: Send "다른 여자랑 영화 봤어" while mood=happy → response shows jealousy + mood becomes 'upset' + next 2 turns retain upset tone.

### Implementation

- [ ] **T030** [P] [US2] Write `src/ai_gf/prompts/persona.md` — 지은 persona: 26세, 서울 거주, 평소 애교+장난기, 진지한 상황에선 진지, 반말. AI 정체 질문에는 끝까지 캐릭터 유지. 사진(`ai_gf.png`)에 부합하는 외형.
- [ ] **T031** [P] [US2] Write `src/ai_gf/agent/triggers.py` — keyword rules from plan.md "State Transition Rules"; expose `analyze(message_text, current_state) -> StateDelta`
- [ ] **T032** [US2] Wire triggers into inbound pipeline: receive → `triggers.analyze` → `state.update_state(delta, reason)` → persona prompt includes new state → LLM
- [ ] **T033** [US2] Implement reactive send path in `app.py`: poll → for owner msg → log inbound → triggers → LLM → log outbound → channel send with 30s–5min jitter
- [ ] **T034** [P] [US2] Write `tests/test_triggers.py` — assert 10 trigger sentences produce expected deltas; assert decay (jealousy −5/h) after 1h
- [ ] **T035** [P] [US2] Manual smoke test: 10-turn jealousy conversation script in `tests/smoke/us2_jealousy.md` (a doc the operator follows by hand)
- [ ] **T036** [US2] Daily response cap guard (25) in `app.py` reactive path

**Checkpoint**: US2 acceptance scenarios 1–3 pass via manual smoke test. SC-002 ≥ 8/10 trigger sentences produce visible jealousy.

---

## Phase 5: User Story 1 - Proactive Greetings (Priority: P1)

**Goal**: Bot sends first messages at time windows without user prompting.

**Independent Test**: Run bot 24h with no inbound messages; verify ≥3 proactive messages distributed across windows (SC-001).

### Implementation

- [ ] **T040** [P] [US1] Write proactive prompt templates: `prompts/proactive_morning.md`, `proactive_lunch.md`, `proactive_evening.md`, `proactive_night.md` — each is a directive appended to persona system prompt: "지금은 {window} 시간이야. 자연스럽게 먼저 한 줄 보내."
- [ ] **T041** [US1] Implement `src/ai_gf/scheduler/proactive.py` — APScheduler with 4 cron triggers (08–10, 12–13:30, 18–20, 22–23:30 KST). Each fires once per window at jittered time.
- [ ] **T042** [US1] Implement `proactive.send_proactive(kind)`: checks daily proactive cap (20) → checks `last_proactive_at` to avoid duplicate per window → builds prompt (persona + state + summary + recent turns + window directive) → LLM → channel send with 30s–5min jitter → records to messages with `trigger_kind`
- [ ] **T043** [US1] State context awareness: if mood=upset → use slightly cooler tone variation of prompt; injected via persona.build_system_prompt
- [ ] **T044** [P] [US1] Write `tests/test_scheduler.py` — assert window selection from current time; assert "already sent in window" suppression; assert daily cap blocks
- [ ] **T045** [US1] Wire scheduler into `app.py`: scheduler runs alongside inbound poll loop; both share state DB
- [ ] **T046** [US1] Verify SC-001 manually: run bot 24h with no inbound, count proactive messages — target ≥3

**Checkpoint**: MVP complete. US1+US2+US5 all functional. Bot can be lived-with for a week.

---

## Phase 6: User Story 4 - Silence Detection and Worry (Priority: P2)

**Goal**: After 4h of owner silence, bot sends worry/sulk message; longer silence → stronger tone.

**Independent Test**: Stop replying for 4h → verify one idle message. Continue silence to 8h → verify second message with escalated tone. SC-001 + manual review of acceptance scenarios.

### Implementation

- [ ] **T050** [US4] Add APScheduler interval job (every 30min) → `scheduler.check_idle()` → if `now - last_user_msg_at > 4h AND now - last_proactive_at > X` → call `send_proactive(kind='idle')`
- [ ] **T051** [US4] Write `prompts/proactive_idle.md` with tone variants by silence-duration bucket (4–8h: 가벼운 걱정, 8h+: 토라짐) and prior mood
- [ ] **T052** [P] [US4] Extend `tests/test_scheduler.py::test_idle_no_double_fire` — ensure same silence window doesn't trigger twice within 2h

**Checkpoint**: US4 scenarios pass.

---

## Phase 7: User Story 3 - Conversation Memory Continuity (Priority: P2)

**Goal**: Bot references events from days ago accurately. Persona/state/memory survive restart.

**Independent Test**: 50-turn conversation over 3 days → restart bot → ask "지난주에 ○○ 이야기했던 거 기억해?" → bot recalls correctly. SC-003 ≥ 70% recall rate.

### Implementation

- [ ] **T060** [US3] Implement `memory.log.do_summarize()` — when >50 unsummarized turns, call aux LLM (qwen2.5:3b) with summary prompt → store summary, mark covered messages as summarized
- [ ] **T061** [P] [US3] Implement `prompts/summarize.md` — Korean summarization prompt focused on facts (사건, 약속, 감정 변화, 인물 언급)
- [ ] **T062** [US3] `persona.build_system_prompt` already loads summary → verify path
- [ ] **T063** [US3] Restart resilience: run bot, send 5 msgs, kill process, restart, assert state/memory continuity (manual)
- [ ] **T064** [P] [US3] Write `tests/test_memory.py` — summary creation, supersedes old, covers_until correct

**Checkpoint**: US3 scenarios pass. SC-003 verified after a week of use.

---

## Phase 8: Operations & Polish

**Purpose**: Make it run unattended.

- [ ] **T070** Pull aux model: `ollama pull qwen2.5:3b` (only if not yet)
- [ ] **T071** Write `scripts/install_launchd.sh` — generates `~/Library/LaunchAgents/com.aigf.bot.plist`, runs `launchctl load`. Plist points to `.venv/bin/python -m ai_gf.app`, logs stdout/stderr to `data/`
- [ ] **T072** [P] Challenge handler: in `channel/instagram.py`, override `instagrapi` challenge_resolver to log + halt sends (no auto-resolve); send a local notification (osascript `display notification`)
- [ ] **T073** [P] Add operational logging: per-message log line with direction, ts, mood-at-time, trigger_kind; rotating file handler 7d
- [ ] **T074** [P] Daily summary script `scripts/daily_report.py` — prints sends, receives, current state, recent triggers (for self-monitoring without opening DB)
- [ ] **T075** Run `quickstart` end-to-end from a clean shell (per plan.md "Quickstart" section)
- [ ] **T076** Run constitution-check on final code: persona always injected (I), whitelist enforced everywhere (II), daily cap + jitter respected (III), no external network besides IG (IV)
- [ ] **T077** Write minimal `README.md` covering setup, run, stop, troubleshooting

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** → no dependencies
- **Foundational (Phase 2)** → blocks all user stories
- **US5 (Phase 3)** → blocks US1, US2, US3, US4 (safety prerequisite)
- **US2 (Phase 4)** → after US5
- **US1 (Phase 5)** → after US5; can run in parallel with US2 if 2 developers
- **US4 (Phase 6)** → after US1 (reuses send_proactive)
- **US3 (Phase 7)** → after US2 (memory needs state-aware messages flowing)
- **Polish (Phase 8)** → after all desired stories

### Within Each Story

- Schema/prompt files [P] can run parallel
- Tests [P] for the same story can run parallel
- Wire-up tasks (T032, T033, T045) are sequential because they touch `app.py`

### Parallel Opportunities

- T002–T006 (setup parallel)
- T012/T013 within Foundational
- T030/T031/T034/T035 within US2
- T040/T044 within US1
- Within Polish: T072/T073/T074

---

## Implementation Strategy

### MVP First (US5 → US2 → US1)

1. Phase 1 Setup
2. Phase 2 Foundational
3. Phase 3 US5 (whitelist) — **STOP and verify** with two-account test
4. Phase 4 US2 (jealousy) — **STOP** and run 10-trigger smoke test
5. Phase 5 US1 (proactive) — **STOP** and run 24h proactive observation

At this point you have a livable bot. Decide whether to continue.

### Incremental Polish

6. Phase 6 US4 (silence detection) — 1 day of work
7. Phase 7 US3 (memory continuity) — 1 day of work + aux model pull
8. Phase 8 Ops — 1 day, then install LaunchAgent

### Solo Dev Estimate

- Phase 1: 30 min
- Phase 2: 2–3 hours
- Phase 3 (US5): 1–2 hours
- Phase 4 (US2): 4–6 hours (most LLM-prompt iteration here)
- Phase 5 (US1): 3–4 hours
- Phase 6 (US4): 2 hours
- Phase 7 (US3): 3–4 hours
- Phase 8: 2–3 hours
- **MVP total** (P1 stories): ~10–14 hours
- **Full v1**: ~18–25 hours

---

## Notes

- [P] = different files, no dependency
- [Story] tag traces task ↔ user story
- Constitution §"Development Workflow" mandates phase-end manual smoke test before next phase
- Daily caps (20 proactive / 25 total) and jitter are NON-NEGOTIABLE per constitution §III — do not "temporarily disable for testing" in production code; use a separate dry-run flag instead
- Account-warmup gate: do NOT activate the bot on a new IG account until ≥ 1 week of manual human use
- LLM response quality is verified manually, not by automated assertion — chase persona consistency, not test count
