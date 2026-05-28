<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0 (MINOR — daily cap thresholds raised)
Modified principles:
  - III. Account Safety First — daily message caps raised from ≤20 to
    ≤30 proactive / ≤50 total outbound. Rationale: 1 week of warmed-up
    operation surfaced no challenge events; the owner wants more
    natural-volume conversation.
Added sections: none
Removed sections: none
Templates requiring updates: none (caps live in .env, not templates)
Follow-up TODOs: none
-->

# AI Girlfriend Chatbot Constitution

## Core Principles

### I. Persona Consistency (NON-NEGOTIABLE)
The girlfriend persona — name, tone, speech patterns, background — MUST remain
stable across sessions, model swaps, restarts, and state transitions. The
system prompt that defines the persona is the authoritative source and MUST be
loaded on every LLM call. Persona drift (e.g., breaking voice when mood
changes) MUST be treated as a bug. Mood, jealousy, and affection are state
variables that color the persona — they do NOT replace it.

**Rationale**: The product value is "feels like a real, specific girlfriend."
Inconsistency breaks the illusion irrecoverably; users do not forgive a
character that changes who she is.

### II. Single-Owner Whitelist
The bot MUST process messages only from a pre-configured owner Instagram user
ID. Inbound DMs from any other account MUST be ignored or auto-discarded at
the channel layer before reaching the agent. There is no admin mode, no
multi-user mode, no group chat. The whitelist is enforced at the earliest
possible point in the inbound pipeline.

**Rationale**: This is a private, single-user companion. Allowing other
senders creates safety, privacy, and account-risk surface area with zero
upside.

### III. Account Safety First
Operational decisions MUST favor Instagram account longevity over throughput
or feature richness. Concrete rules:
- Daily proactive message cap: ≤ 30 messages.
- Daily total outbound cap (proactive + reactive): ≤ 50 messages.
- Inter-message jitter: 30s–5min randomized delay.
- Polling interval: 30–90s randomized (not fixed cadence).
- New accounts MUST be warmed up manually for ≥ 1 week before bot activation.
- Session credentials persisted; re-login frequency minimized.
- A pinned residential proxy SHOULD be used; IP rotation MUST NOT happen
  within a session.

If a feature trade-off pits "more chat" against "lower ban risk," ban risk
wins.

**Rationale**: `instagrapi` uses Instagram's private API. Account loss = full
channel loss. Recovery requires creating + warming a new account, which
takes days. Conservative limits are cheaper than recreation.

### IV. Local-First Data
Conversation history, persona state, and user identifiers MUST stay on the
local machine. SQLite files MUST NOT be uploaded to remote storage, telemetry
services, or LLM-provider logs. The LLM runs locally via Ollama. The only
external traffic is the Instagram DM channel itself (irreducible) and any
explicit, user-approved integration.

If an image or attachment is sent by the user and requires interpretation, a
local multimodal model SHOULD be used; an external API MAY be used only if
the user has explicitly opted in for that specific feature.

**Rationale**: Conversations are intimate. The user chose local LLM
specifically to avoid third-party data exposure. Defaulting to local
preserves that contract.

## Technical Constraints

- **Language**: Python 3.11+, managed via `uv`.
- **LLM runtime**: Ollama (`http://localhost:11434`). Primary model:
  `qwen2.5:14b-instruct-q4_K_M`. Auxiliary small model (emotion / summary)
  permitted.
- **Channel**: Instagram DM via `instagrapi`. Session persisted to
  `data/ig_session.json`. No other channels in v1.
- **Storage**: SQLite for state + memory. File-based, no server DB.
- **Scheduler**: APScheduler for proactive triggers.
- **Secrets**: `.env` only. MUST be git-ignored. No secrets in code, logs,
  or commits.

## Development Workflow

- **Spec-driven**: Every feature MUST go through spec-kit
  (`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
  `/speckit-implement`). Drive-by code is rejected.
- **No TDD requirement**: Tests are written for the channel layer (login,
  send, receive, whitelist) and the state machine (mood/jealousy transitions).
  LLM output is verified manually, not via automated assertion. New features
  outside these layers MAY ship without tests if behavior is observable in
  the channel.
- **Manual verification gate**: Each phase ends with a manual conversation
  smoke-test (10+ turns) before the next phase starts.
- **Single-branch development**: Feature branches OK, but no long-running
  parallel features. One initiative at a time.

## Governance

This constitution supersedes ad-hoc preferences. Changes require:
1. A spec-kit feature spec that explicitly notes the constitution amendment.
2. Version bump per semver (MAJOR for principle removal/redefinition, MINOR
   for new principle/section, PATCH for clarification).
3. Update of dependent templates if affected.

Compliance MUST be checked at the start of every `/speckit-plan` review:
- Does the plan respect single-owner whitelist? (II)
- Does the plan stay within daily caps and jitter rules? (III)
- Does the plan keep data local by default? (IV)
- Does the plan preserve persona invariants? (I)

A plan that violates any principle MUST either be revised or trigger a
constitution amendment in the same change set.

**Version**: 1.1.0 | **Ratified**: 2026-05-21 | **Last Amended**: 2026-05-28
