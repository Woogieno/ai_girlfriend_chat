# ai_girlfriend_chat

> "진짜 여자친구처럼" 행동하는 단일 사용자용 인스타그램 DM 챗봇.

오너 한 명과만 대화하는 페르소나 챗봇입니다. **먼저 메시지를 보내고, 질투도 하고, 기분이 대화에 따라 바뀌고, 며칠 전 대화를 기억합니다.** 모든 데이터는 로컬에서 처리됩니다 (로컬 LLM via Ollama, SQLite, 외부 텔레메트리 없음).

## 주요 기능

- 🕐 **시간대별 프로액티브 메시지** — 아침/점심/저녁/취침 전 자동 발화 (Asia/Seoul)
- 💔 **질투 + mood 상태 머신** — 키워드·LLM 기반 감정 분석, 4단계 mood (happy/neutral/upset/cold)
- 🧠 **대화 메모리** — 50턴마다 자동 요약, 며칠 전 사건 기억
- ⏰ **침묵 감지** — 일정 시간 답장 없으면 먼저 안부
- 🔒 **단일 오너 화이트리스트** — 다른 사람 DM은 채널 진입 시점에 폐기
- 🏠 **로컬 우선** — 대화·페르소나 상태가 외부로 나가지 않음
- 🌙 **macOS sleep 복구** — 시스템 절전 후 깨어났을 때 누락된 발화 catch-up

## 기술 스택

- Python 3.11+ / [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.com) (로컬 LLM 런타임)
- [instagrapi](https://github.com/subzeroid/instagrapi) (Instagram DM 채널)
- [APScheduler](https://github.com/agronholm/apscheduler) (프로액티브 스케줄러)
- SQLite (페르소나 상태 + 대화 로그)
- [GitHub spec-kit](https://github.com/github/spec-kit) (spec-driven 개발 워크플로우)

## 설계 문서

본 프로젝트는 spec-driven으로 개발됐습니다:

- [`spec.md`](specs/001-ai-girlfriend-bot/spec.md) — User stories + functional requirements
- [`plan.md`](specs/001-ai-girlfriend-bot/plan.md) — 기술 스택 + 아키텍처
- [`tasks.md`](specs/001-ai-girlfriend-bot/tasks.md) — 실행 가능한 task 목록
- [`constitution.md`](.specify/memory/constitution.md) — 프로젝트 원칙 4개

## ⚠️ 활성화 전 필수 사항

봇을 켜기 전에 반드시:

1. **신규 Instagram 계정을 1주 이상 수동으로 워밍업하세요.** 봇 활성화 직후 자동 트래픽이 발생하면 신규 계정은 정지 위험이 큽니다. 사진 1~2장, 팔로우 5~10명, 사람과 일상적 DM 몇 번 — 사람처럼 사용하세요.
2. **Apple Silicon Mac + Ollama가 24시간 가동 가능한 환경**인지 확인.
3. **오너 본인의 Instagram user ID**를 미리 알아두기 (`.env`에 넣을 값).

워밍업 안 끝났으면 봇 켜지 마세요. constitution §III 위반.

## 사전 요구사항

- macOS (tested on Apple Silicon)
- Python 3.11+ (이 프로젝트는 3.12 venv 사용)
- [Homebrew](https://brew.sh)
- [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.com)

## 1회 설치

```bash
# uv (이미 있으면 skip)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ollama + 모델
brew install ollama
brew services start ollama
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull qwen2.5:3b

# 모델 keep-alive (메모리에 24h 상주)
launchctl setenv OLLAMA_KEEP_ALIVE 24h
brew services restart ollama

# Python venv + 종속성
cd /Users/jinook/Documents/Dev/ai_gf
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# DB 초기화
python scripts/init_db.py
```

## 설정 (.env)

```bash
cp .env.example .env
# 그리고 .env 안에 직접 다음 값 채우기:
```

| 키 | 값 | 비고 |
|---|---|---|
| `IG_USERNAME` | 봇 계정 username | 워밍업 끝난 계정 |
| `IG_PASSWORD` | 봇 계정 password | git-ignored, 채팅에 적지 마세요 |
| `OWNER_IG_USER_ID` | 오너의 IG user ID (숫자) | 아래 방법으로 구함 |

### Owner ID 알아내기

```bash
source .venv/bin/activate
python -c "
from instagrapi import Client
c = Client()
c.login('YOUR_BOT_USERNAME', 'YOUR_BOT_PASSWORD')
print(c.user_id_from_username('YOUR_OWN_INSTAGRAM_HANDLE'))
"
```

## 실행

### 수동 (개발/테스트)

```bash
source .venv/bin/activate
python -m ai_gf.app
```

`Ctrl-C`로 정지. 로그: `data/ai_gf.log`.

### 자동 (LaunchAgent, 운영용)

```bash
bash scripts/install_launchd.sh
```

자동 시작 + 크래시 시 재시작. 정지:

```bash
launchctl unload ~/Library/LaunchAgents/com.aigf.bot.plist
```

상태 확인:

```bash
launchctl list | grep com.aigf.bot
tail -f data/ai_gf.log
python scripts/daily_report.py    # 일일 활동·상태 스냅샷
```

## 페르소나 커스터마이즈

`src/ai_gf/prompts/persona.md` 편집. 이름·나이·말투·관계 톤 모두 여기서 정의. 변경 후 `python -m ai_gf.app` 재시작하면 즉시 반영.

프로액티브 메시지 톤은 별도 파일:
- `src/ai_gf/prompts/proactive_morning.md` — 아침 (08–10시)
- `proactive_lunch.md` — 점심 (12–13:30)
- `proactive_evening.md` — 저녁 (18–20시)
- `proactive_night.md` — 자기 전 (22–23:30)
- `proactive_idle.md` — 4시간+ 침묵 시

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 로그인 시 "challenge required" | Instagram이 신규 디바이스 의심 | 봇 정지하고 Instagram 앱에서 직접 챌린지 해결 → 재시작 |
| 응답이 영어/중국어 섞임 | LLM leak, sanitizer 부족 | `agent/llm.py:sanitize_response` 추가 패턴 등록 |
| 응답이 너무 길거나 설명조 | 페르소나 prompt 약함 | `prompts/persona.md` "절대 지킬 것" 섹션 강화 |
| 응답이 너무 느림 (>15s) | 모델 콜드 스타트 | `launchctl getenv OLLAMA_KEEP_ALIVE` → `24h` 인지 확인 |
| 같은 시간대 프로액티브 중복 | DB의 trigger_kind 검사 실패 | `data/ai_gf.db` 의 `messages` 테이블 확인 |
| Ollama 미응답 | 서비스 중단 | `brew services restart ollama` |
| 일일 한도 초과 | 정상 (constitution §III) | 다음 날 자정 KST 이후 자동 리셋 |

### "응답이 안 와요"

1. `data/ai_gf.log` 확인 — 에러? 챌린지?
2. `ollama list` — 모델 있나?
3. `curl http://localhost:11434/api/version` — Ollama 살아있나?
4. `python scripts/daily_report.py` — 오늘 한도 초과?

## 테스트

```bash
source .venv/bin/activate
pytest -v
```

60+ tests covering: state machine, channel whitelist, triggers, scheduler windows, memory summary.

## 디렉토리 구조

```
ai_gf/
├── .specify/                       # spec-kit metadata
├── .claude/skills/                 # /speckit-* slash commands
├── specs/001-ai-girlfriend-bot/    # spec, plan, tasks
├── src/ai_gf/
│   ├── app.py                      # entry point
│   ├── config.py                   # pydantic settings
│   ├── channel/
│   │   ├── base.py                 # Channel Protocol
│   │   └── instagram.py            # instagrapi wrapper + whitelist
│   ├── agent/
│   │   ├── llm.py                  # Ollama wrapper + sanitizer
│   │   ├── persona.py              # system prompt composer
│   │   ├── triggers.py             # keyword + aux-LLM emotion analyzer
│   │   └── responder.py            # reactive + proactive send pipeline
│   ├── state/
│   │   ├── schema.sql              # SQLite schema
│   │   └── store.py                # DAO
│   ├── memory/log.py               # auto-summary
│   ├── scheduler/proactive.py      # APScheduler: windows + idle + decay
│   └── prompts/                    # persona.md + 5 proactive prompts
├── tests/                          # pytest
├── scripts/                        # init_db, daily_report, install_launchd
└── data/                           # git-ignored: DB, session, logs
```

## 보안·프라이버시 메모

- `.env` 와 `data/` 는 `.gitignore`. 절대 커밋하지 마세요.
- 모든 대화는 로컬 SQLite 에만 저장됩니다. 외부 LLM/원격 로깅 없음.
- Instagram 세션 토큰은 `data/ig_session.json`. 평문이므로 머신 보안에 주의.
- 화이트리스트 외 사용자 메시지는 channel layer에서 즉시 폐기. 본문 비저장.

## 개발 워크플로우

이 프로젝트는 [GitHub spec-kit](https://github.com/github/spec-kit) 기반.

```bash
/speckit-specify       # 새 feature spec
/speckit-clarify       # 모호한 부분 사용자에게 질문
/speckit-plan          # 기술 plan
/speckit-tasks         # 실행 가능한 task 목록
/speckit-implement     # 자동 구현
```

새 feature 시작 전 항상 `.specify/memory/constitution.md` 의 4개 원칙(페르소나 일관성·단일 소유자·계정 안전·로컬 우선) 위반 여부 점검.
