# Oracle 핸드오프 — 2026-06-07 세션

> **목적**: 다음 세션이 방향을 바로 잡고 이어가도록, 이번 세션의 **모든 결정·구현·다음 단계**를 정리한다.
> 딥리서치 원문 정리는 [`docs/research/`](./research/) 참조. 벤치마크는 [`docs/benchmark-rosebud-mem-memex.md`](./benchmark-rosebud-mem-memex.md).
> **다음 세션은 이 문서부터 읽고 시작할 것.**

---

## 0. Oracle 한 줄 + 스택

**Oracle** = 개인 일상 **디스커버리 채팅 동반자 + 비서**. 캡처(사진/영상/음성/텍스트) → **즉답 인사이트**(LLM) + **일/주/월 저널** + **자연어 질의**(임베딩 검색).

- **스택**: Flutter(앱) + FastAPI(`backend/`) + MongoDB + **Nest**(별도 LLM 게이트웨이, `~/projects/nest/`)
- **경로**: oracle = `~/projects/oracle`, nest = `~/projects/nest`
- **정본(SoT)**: vault 평문 마크다운(`corpus/YYYY/MM/DD.md`). MongoDB는 메타/검색 캐시.
- **핵심 원칙**: 모든 LLM 호출은 **Nest 게이트웨이 경유**(`nest_client`/`agent.llm`). 모델은 **설정(TASK_ALIAS env / 폰 LLM picker)에서 선택** = 모델 agnostic.

---

## 1. 커밋 현황 (이번 세션)

| 커밋 | repo | 내용 |
|---|---|---|
| `d7c7757` | oracle | 임베딩 검색 · 소리/영상 캡처 · 맥락 주입 · api 타임아웃/로깅 · UI 개편(탭) |
| `94e737a` | nest | `/api/embed` 임베딩 엔드포인트 + dispatch audio 첨부 |
| `ac26452` | oracle (HEAD) | **agent 모듈 + 사진 3단계** |

- oracle HEAD = `ac26452`, branch `main`, **push 안 함**(로컬만).
- nest: `db.py`·`deploy/seed_registry.py`·`tests/test_dispatch.py`는 **내 작업 아닌 기존 변경**이라 커밋 안 하고 남겨둠(`git status`에 M으로 남아있음 — 사용자 확인 필요).

---

## 2. 확정된 설계 (상세)

### 2.1 메모리 아키텍처 ⭐ (다음 세션 핵심)

리서치(`research/memory-hierarchy.md`) + 사용자 결정 종합. **요약-of-요약은 폐기, 서술형 저널로.**

| 계층 | 내용 | 보존/용도 |
|---|---|---|
| **워킹 메모리 (롤링 30일)** | 지난 ~29일 **일 저널** + **오늘 raw 캡처** | 즉답 인사이트에 **항상 주입**. 자정에 클리어+재구성. **prompt caching** 대상 |
| **일 저널** (`journals`, day) | 그날을 **일기처럼 시간순 서술**(요약❌) | **무기한 보존** + 임베딩 = **검색 1차 소스** |
| **주 저널** (`journals`, week) | 한 주 **저널 서술**(요약❌) + **LLM 피드백** | 회고 |
| **월 회고** (`journals`, month) | 그달 일/주 저널 재료로 **서술 회고 + 피드백** (요약-of-요약❌, 압축 누적 아님) | 회고 |
| **검색** | 일 저널 임베딩, **시간 상한 없음** | 3요소 스코어: **유사도 + recency(지수감쇠) + importance(reaction 신호)** |
| **원본 미디어** | 사진/영상/오디오 파일 | **6개월 age-out** (내용은 저널 텍스트에 남음) |

**핵심 결정 근거**:
- 분류는 시간보다 **기능 축**: 원본 캡처=episodic, 다이제스트=semantic. 자정 배치 = consolidation(승급).
- **반복 요약은 희귀 디테일을 잃는다(드리프트)** → 원본 평문 보존이 방어책. Oracle은 vault 평문 보존하니 이미 맞음. **그래서 "요약" 대신 "서술 저널"로** 가서 손실 자체를 회피.
- **단기 맥락 = 30일**(하루는 짧다는 사용자 피드백). "1주 상한" 같은 시간 윈도우가 아니라, **검색은 보존(무기한) 전체에서 관련도로** 끌어온다.

> **주의**: 현재 `digest.py`의 일 다이제스트는 **"요약" 프롬프트** → 이걸 **"일기 서술"로 바꿔야 함**. 주/월 저널은 신규.
> 현재 `embedding.py`/`query.py`의 검색 임베딩은 `records`(캡처별)에 있음 → **일 저널(일단위)로 옮겨야 함**. 3요소 스코어도 아직 미구현(현재는 유사도+최근순 fallback만).

### 2.2 Prompt Caching (30일 워킹메모리 경제성)

리서치(`research/prompt-caching.md`) 결론:
- **Claude API `cache_control`이 유일하게 적합** (명시적 prefix 캐싱, 첫 write 후 read 0.1× = ~90% 절감, usage로 hit 관측). `system` 블록에 `ttl:"1h"`.
- **gemini CLI(`-p`)로는 캐싱 불가** (인자 없음 + 구독 OAuth 미지원). → Gemini는 캐싱 경로 아님, **Workspace 도구 + 보조 모델**로만.
- OpenAI 자동 캐싱(제어 불가, 5~10분 소멸).
- **TTL ↔ 자정 재구성**: 자정엔 "교체만"(무효화 코드 불필요). **진짜 리스크 = 띄엄띄엄 캡처 시 TTL 만료** → `ttl:"1h"` + **자정 cron keep-warm 프리워밍**(`max_tokens:0`).
- **설계 방침**: cache_prefix를 prompt와 분리해 넘기는 건 **공통**. 고른 모델이 anthropic API면 cache_control 자동 적용, 로컬/CLI면 그냥 합쳐서 동작(**graceful**). 즉 캐싱은 "되면 보너스". (`agent/llm.py`에 `cache_prefix` 인자 이미 hook 됨 — Nest 쪽 미구현)

**Nest 수정 필요** (`nest/backends/api_backend.py`):
1. `call_anthropic`: 고정 prefix → `system=[{...,"cache_control":{"type":"ephemeral","ttl":"1h"}}]`, 가변(이미지/오늘 캡처)은 messages 뒤로. content 순서 = 고정 앞 / 가변 뒤.
2. `_result`에 `cache_read_input_tokens`/`cache_creation_input_tokens` 추가(hit 검증).
3. 30일 컨텍스트 직렬화는 **결정론적**(`sort_keys=True`, 타임스탬프/UUID 배제).
4. **선결 이슈**: `call_anthropic`의 `thinking={"type":"enabled","budget_tokens":...}` 분기는 **Opus 4.8/4.7에서 에러**(budget_tokens 제거됨) → `adaptive`+effort로 고쳐야.
5. Nest `dispatch`/`server.py /api/call`이 `cache_prefix`(또는 system) 인자를 받아 전파하도록 인터페이스 확장.

### 2.3 사진 3단계 ✅ (backend 구현 완료)

리서치(`research/photo-pipeline.md`) — CCoT describe-then-reason. **`agent/vision.py` 구현됨.**
```
1) analyze : VLM → JSON {objects, attributes, relationships, scene, ocr_text}
2)+3) reason: 이미지 + 분석 JSON + user_input + 맥락/기억 → {comment, suggestion}
            (visual grounding 위해 이미지·JSON 재투입, VLM 2회 호출)
```
- `ingest.py`: 사진 있으면 `vision.process()`, 텍스트/오디오만이면 단일 인사이트(기존).
- record: `analysis`(JSON)·`suggestion` 신규, `insight.text`=comment, `vlm.caption`=분석 한줄요약(`_summarize_analysis`).
- vault 라벨: `**분석**`/`**코멘트**`/`**제안**`. embedding build_text에 suggestion 포함.
- **남은 것: Flutter 표시**(analysis/suggestion 카드).

### 2.4 agent 모듈 ✅ (골격 완료)

`backend/agent/`:
- `llm.py` — 모든 LLM 호출 단일 통로(Nest 래퍼). `call/call_text/embed/embed_one/default_alias`. `cache_prefix` 인자 hook(Nest 미구현이라 현재 graceful 무시).
- `vision.py` — 사진 3단계.
- **예정**: `memory.py`(워킹30일+저널 검색·주입, 3요소), `chat.py`(대화/질의+도구), `tools/`(workspace, calendar, summarize).
- **이관 예정**: `ingest`(insight)·`query`·`digest`의 LLM 로직을 점진적으로 agent로.

### 2.5 대화 모드 (히스토리 탭)

- 기록 탭 = **입력**(캡처, ingest) / 히스토리 탭 = **대화**(출력, query).
- 히스토리 탭에 캡처 record + Q&A를 **한 타임라인에 섞기** + 하단 질문 입력창 → `query` → 답변 버블 + 근거 record 카드.
- **대화 저장**(Mongo `conversations` 컬렉션 신규).
- 검색 = 자연어 질의로 흡수(AppBar 검색 아이콘 통합 가능).
- `query.py`(→`agent/chat.py`)는 거의 재활용.

### 2.6 외부 연동 (사이드로드 전용 — 권한 자유)

- **배포 = 개인 사이드로드 전용** → SMS/통화/알림 권한 자유(Play 정책 제약 없음).
- **알림 전체 읽기**: `notification_listener_service`(NotificationListenerService, 사용자 1회 수동 허용).
- **SMS 읽기**: `READ_SMS` + telephony 플러그인. (안 읽은 SMS 요약이 핵심 활용)
- **통화 기록**: `READ_CALL_LOG`.
- **캘린더**: **device_calendar(기기 읽기) + Google Calendar API(OAuth 쓰기) 둘 다**.
- **우선순위**: 안읽은 SMS 요약 → 알림 전체 → 캘린더 → 통화 (전부).
- 흐름: 수집(Flutter 플러그인+권한) → backend → **agent가 요약·인사이트** → 푸시.

### 2.7 Google Workspace = Gemini CLI extension

- **Gemini CLI 공식 Workspace extension**(MCP): `gemini extensions install https://github.com/gemini-cli-extensions/workspace`
- Gmail(10)·Calendar(8)·Drive(8)·Docs/Sheets/Chat 등 50+ 도구. **로컬 실행 + 사용자 OAuth로 직접**(클라우드 중계 없음).
- **경로 A(채택)**: chocolat gemini CLI에 extension+OAuth → gemini가 Workspace 도구 보유 → agent가 "메일 요약/일정 잡기" 위임. Oracle 코드 최소.
- **검증 필요**: Nest가 gemini를 `-p`(비대화) 단발로 부르는데 거기서 **MCP 도구가 자동 호출되는지** 실제 확인 필요.
- **사용자 액션**: chocolat에서 구글 OAuth 1회 인증.

### 2.8 영상/음성 모델 인식 (보류 — 모델 결정 대기)

- 현재 오디오/영상은 **캡처·저장만**, 인식 보류.
- **gemini CLI는 멀티모달(이미지/오디오/영상) 미지원 확정**([이슈 #15532](https://github.com/google-gemini/gemini-cli/issues/15532) closed not planned). "영상 O 오디오 X" 모델은 영상의 소리를 못 들음(프레임만).
- **로컬 영상+오디오 인식 후보**(Apple Silicon/mlx):
  - **Qwen3.6(=qwen-vlm, 이미 milk에 있음)** — 영상 네이티브, **단 오디오 미지원**(VL 계열).
  - **MiniCPM-o 4.5** (9B, omni=이미지+오디오+영상, mlx/llama.cpp/ollama) — 비-Qwen 베스트, **오디오까지 한 모델**.
  - **Gemma 4 12B** (Google, encoder-free, text+image+**video+native audio**, ~16GB, mlx-vlm Day-0, Apache 2.0) — 오디오 30초/영상 60초 제한. **E2B/E4B/12B만 오디오 지원, 26B/31B는 영상만**.
- **로컬 추론 머신**: milk(M5 Max/128GB, qwen-vlm `192.168.68.100:8080`) 또는 croissant(M3 Ultra/512GB). 12B급은 여유.
- **결정 대기**: 어떤 모델로 오디오/영상 인식을 살릴지. (논의했으나 미확정 — Gemma4 12B 또는 MiniCPM-o가 유력, "설정에서 선택" 방침)

---

## 3. 구현 현황

### ✅ 완료 (커밋됨)
- **임베딩 검색**: Nest `/api/embed`(openai/openai_compat) + `embedding.py`(brute-force 코사인, graceful) + `query.py`(top-k→LLM). `ORACLE_EMBED` alias 설정 시 작동, 미설정이면 최근순.
- **소리/영상 캡처**: `corpus.save_audio/save_video`, `ingest` audio/video 인자, `/ingest` 멀티파트, Flutter 녹음(record 패키지)·영상(카메라 long-press→탭버튼·갤러리). **인식은 보류**(저장만).
- **맥락 주입**: `ingest._recent_context`(현재 30분/8개, `.env`) → **30일 롤링으로 바꿔야 함**.
- **api 타임아웃+로깅**: `api.dart` 전면 재작성 + `applog.dart`(콘솔+파일+인메모리).
- **UI 개편**: 탭 홈(placeholder)/히스토리(채팅+pull-refresh)/기록(카메라+[사진][영상][음성]+텍스트+전송, 우상단 반투명 갤러리), 첫 실행=기록 탭, 음성=순수녹음(STT 제거), resume refresh.
- **agent 골격 + 사진 3단계 backend** (위 2.3/2.4).

### ⬜ 남음 (다음 세션 로드맵 = 4번)

---

## 4. 다음 세션 로드맵 (우선순위순)

1. **Flutter 사진 표시** — `models.dart` Record에 `analysis`/`suggestion` 추가, `main.dart` 채팅 카드에 코멘트+제안(+분석 펼치기) 표시.
2. **메모리** (가장 큰 덩어리):
   - `digest.py` 일 다이제스트 → **일기 서술**로 프롬프트 변경 + `journals` 컬렉션(day) 저장.
   - **주/월 저널** 신규(서술+피드백), 각각 cron.
   - 검색 임베딩 `records` → **일 저널**로 이동, **3요소 스코어**(유사도+recency+reaction) 구현 → `agent/memory.py`.
   - **워킹 30일 주입**: 즉답 인사이트에 지난 일 저널 ~29 + 오늘 raw 주입(`_recent_context` 대체).
   - **Nest `call_anthropic` 캐싱**(2.2) + cache_prefix 전파 + Opus 4.8 thinking 호환.
   - 6개월 미디어 age-out cron.
3. **대화 모드** (2.5): 히스토리 탭 타임라인 + 입력창 + `conversations` 저장 + `agent/chat.py`.
4. **입력소스** (2.6): SMS→알림→캘린더→통화. Flutter 플러그인+권한 + backend 수신 + agent 요약.
5. **Workspace** (2.7): gemini CLI extension + OAuth + Nest 경유 도구 호출 검증.
6. **영상/음성 인식** (2.8): 모델 결정(Gemma4 12B / MiniCPM-o) → milk/croissant 서빙 → Nest 등록 → ingest 연결.

---

## 5. 인프라 사실 (fleet 대시보드 기준, 2026-06-07)

> SoT = fleet 대시보드 `http://100.65.74.85:8000/dashboard/` (`/fleet` 선언, `/infra` 라이브).

**머신**:
| 이름 | 사양 | 역할 |
|---|---|---|
| **bert** | M5 / 24GB | 헤드 머신(Claude Code 실행처) |
| **chocolat** | M4 Pro / 24GB | **메인 서버·베스천**: Nest(`:7780`)·MongoDB·oracle backend(`:8001`) |
| **milk** | M5 Max / 128GB | 로컬 Qwen 클러스터 — **qwen-vlm 호스팅** (`192.168.68.100:8080`) |
| **croissant** | M3 Ultra / 512GB | **AI 추론 메인** (`100.94.132.72:7780`) — glm/kimi/qwen397 |
| **camem** | (미상, offline) | 빌드 전용(까망베르치즈 iOS) — 추론처 아님 |
| almond/mint/cheese | M4·M2 / 16GB | 트레이딩·공용·Orchard |

**Nest 등록 모델**(`/api/models`): claude(cli, opus, vision)·codex(cli, gpt-5.5)·gemini(cli, gemini-3-pro-preview, vision)·qwen-vlm(api openai_compat, mlx Qwen3.6-27B-8bit, vision, milk)·qwen397(croissant)·glm/kimi(disabled).

**MongoDB**: self-hosted standalone, `mongodb://localhost:27017`, db `oracle`, 컬렉션 `records`/`threads`/`index_meta` (+ 신규 예정 `journals`/`conversations`). **Atlas 아님** → native vector search(8.2+ mongot)는 preview+운영부담이라 미사용, brute-force(numpy) 채택.

**Nest 호출**: oracle `config.py` `NEST_BASE_URL=http://chocolat...:7780`, `X-Nest-Token`. CLI 백엔드는 chocolat에서 subprocess(구독 OAuth, `HOME`/`CLAUDE_CONFIG_DIR` 전환).

---

## 6. 미해결 / 주의사항

- **backend venv Pillow 미설치** → `ingest._exif_location` graceful 실패 중(EXIF GPS 안 잡힘). `requirements.txt`엔 있으니 운영 배포 땐 깔리지만 개발 venv 확인.
- **Nest `call_anthropic` Opus 4.8/4.7 비호환**: `thinking budget_tokens` → `adaptive`+effort 필요(캐싱과 별개 선결).
- **gemini CLI 멀티모달 미지원**: 이미지조차 `@path`로 안 받음(이슈 closed). 사진 인식은 claude/qwen-vlm으로(gemini 아님).
- **nest `db.py`/`seed_registry.py`/`test_dispatch.py`** 기존 변경 미커밋 — 사용자 확인.
- **gemini CLI `-p`에서 MCP/Workspace 도구 동작 여부** 미검증.
- numpy는 oracle backend venv에 설치됨(`pip install numpy` 했음).

---

## 7. 딥리서치 결과물

이번 세션에서 돌린 딥리서치(각 ~100만+ 토큰, 적대적 검증). 상세는 각 파일:
- [`research/memory-hierarchy.md`](./research/memory-hierarchy.md) — 계층적 메모리(단기/장기, consolidation/forgetting, 3요소 검색)
- [`research/photo-pipeline.md`](./research/photo-pipeline.md) — 사진 3단계(CCoT/SPARC/Img2Prompt, JSON 씬그래프)
- [`research/prompt-caching.md`](./research/prompt-caching.md) — 30일 워킹메모리 캐싱(Claude API only, TTL/keep-warm, Nest 수정점)
- [`benchmark-rosebud-mem-memex.md`](./benchmark-rosebud-mem-memex.md) — 경쟁 서비스 벤치마크 + Memex 코드 분석

---

## 8. 다음 세션 시작 제안

1. 이 문서 + `research/` 읽기.
2. **Flutter 사진 표시**부터 (사진 3단계 backend는 됐으니 폰에서 보이게) → 그 다음 **메모리**(가장 큼).
3. 막히면: 설계는 다 위에 있음. 구현만 남았고, **메모리/캐싱이 서로 얽혀** 있으니 2번을 한 덩어리로.
