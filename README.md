# Oracle

일상을 사진·텍스트·음성으로 던지면 LLM이 계속 반응하며 알려주는, **채팅 동반자이자 비서**.

> 구 코드네임 'Oracle'(인벤토리 앱)에서 분기 — 그쪽은 **finder**(`~/projects/finder`).

## 무엇을 하는가

- 폰 카메라로 셔터 1회, 음성/텍스트 코멘트 → 즉시 LLM이 의견·인사이트로 응답 (fire-and-forget, 비동기 인입+폴링)
- **대화 모드** — 히스토리 탭 하단 입력으로 동반자와 자유 대화 (워킹메모리+3요소 검색 컨텍스트)
- 매일 **자정 다이제스트** 자동 생성 — 그날의 테마·발견·환기 항목
- **자연어 검색** — "지난주 마우스 관련 뭐였더라?" → 답변 + 근거 record 썸네일 카드
- **펜딩 환기** — 며칠째 무언급된 thread 자동 점검 (silent drop 방지)
- **외부 공유 인텐트** — 카카오톡·갤러리·브라우저에서 사진·영상·텍스트를 Oracle로 바로 던지기

비슷한 카테고리(자동 라이프로깅 Rewind/Limitless, 텍스트 저널링 Day One/Rosebud, OSS 캡처 Memex)와 차이:
- **의도적 캡처** + **즉답 인사이트** + **자정 능동 환기** 세 다리. 자동 캡처 아님.
- **클라우드 LLM (Nest 게이트웨이)** — 모델·effort·계정을 게이트웨이에서 일괄 관리, 폰 picker로 동적 전환

## 아키텍처 — 3 레이어

1. **Layer 1 (인입)** — 캡처 → VLM 캡션 + LLM 즉답 → Record로 평문 vault(`corpus/`)에 append + MongoDB 메타. *실시간*
2. **Layer 2 (분류)** — Record에 thread_ids · type · tags · location 부착. *자정 LLM*
3. **Layer 3 (다이제스트)** — 닫힌 일별 다이제스트(`digest/YYYY-MM-DD.md`) + 누적 상위 인덱스(`index/master.md` + MongoDB `index_meta`) + 펜딩 thread 점검 + reaction(취향 신호) 누적. *자정 LLM + 코드*

원칙: **vault = 정본 평문(불변)**, MongoDB = 캐시·인덱스(손실 시 vault에서 재생성).

## 디렉토리

```
corpus/                # 정본 vault — 날짜별 마크다운 + 이미지/오디오/영상 (gitignored)
digest/                # 일 저널 (자정 생성, gitignored)
journal/               # 주/월 회고 (gitignored)
index/                 # 사람용 master.md 검색 진입점 (gitignored)
backend/               # FastAPI (chocolat에서 LaunchAgent로 영구화)
  main.py              # 미들웨어 + entry
  api/                 # 도메인 라우터 (얇음): ingest·records·journal·threads·query·index·nest
  ingest.py            # 캡처 파이프라인 (Layer 1)
  nightly.py           # 자정 오케스트레이션 (일 + 월요일 주간 + 1일 월간)
  classify.py          # thread_judge + type/tags 분류 (Layer 2)
  journal.py           # 일/주/월 서술 저널 생성·저장·조회 (Layer 3)
  index.py             # 상위 인덱스 (master.md + index_meta)
  query.py             # 자연어 검색·질의 (agent.memory 사용)
  nightly_common.py    # 자정 공유 헬퍼 (records_brief·resolve_alias·parse_json_safe)
  agent/               # llm(Nest 래퍼+cache_prefix hook) · vision(사진3단계) · memory(3요소 검색+워킹메모리)
                       # · chat(대화 모드 MVP — 호문쿨루스 연동 시 교체 경계)
  nest_client.py       # Nest 게이트웨이 HTTP 클라이언트
  db.py                # MongoDB (records · threads · index_meta · journals)
  corpus.py            # vault read/append
  embedding.py         # record/journal 임베딩 생성·backfill
  threads.py           # thread 메타·active·silent 점검
  config.py            # env·task→alias 매핑
app/                   # Flutter (Android, namespace: studio.camembertcheese.oracle)
  lib/
    main.dart · app.dart            # 엔트리·테마
    core/record_store.dart          # records+pendings SSOT (ChangeNotifier)
    features/capture/               # 카메라·영상·오디오·갤러리·공유인텐트 + 전송
    features/chat/                  # 히스토리 타임라인·버블·리액션·편집
    features/home/                  # 앱 셸(탭·생명주기·모델선택)
    features/notifications/         # 로컬 알림
    api.dart · models.dart          # REST 클라이언트·모델
    query_screen.dart · digest_screen.dart · index_screen.dart · llm_picker.dart · onboarding_screen.dart
deploy/                # chocolat LaunchAgent plists
  h59.oracle.backend.plist        # backend (KeepAlive, 부팅 자동)
  h59.oracle.midnight.plist       # 매일 00:05 자정 배치 cron
  h59.oracle.mongo-backup.plist   # 매주 일 03:00 MongoDB 백업
  h59.oracle.vault-backup.plist   # 매일 03:20 vault(정본) 스냅샷 백업
  backup-mongo.sh · backup-vault.sh
```

## LLM 호출 — Nest 게이트웨이

`~/projects/nest` (`chocolat:7780`, 토큰 인증). 모든 LLM 호출이 Nest 통과 — provider/effort/account 셋업은 Nest admin(`/admin`)에서.

**동적 alias 결정 chain**:
1. 폰 LLM picker 선택 (`(자동)` 또는 특정 모델 — `claude`/`codex`/`gemini`/`qwen-vlm`/`trio` council)
2. `.env` 명시 (`ORACLE_VLM`, `ORACLE_INSIGHT`, `ORACLE_DIGEST` 등)
3. Nest enabled 첫 모델 (매 호출 fresh fetch, 캐시 X)

Nest add/remove하면 다음 호출에 즉시 반영.

## 인프라 (현재 셋업)

| 노드 | 역할 |
|---|---|
| **bert** (`portable`) | 개발·빌드 머신. 코드 작성·APK 빌드만 |
| **chocolat** (`100.65.74.85`) | 메인 서버. backend·MongoDB·Nest 다 여기 |
| Z Fold7 폰 | Flutter 앱. Tailscale magic DNS로 chocolat 도달 |

**Tailscale magic DNS** (`chocolat.tail575fea.ts.net:8001`) — bert 위치·폰 IP 변동 무관.

## 실행 (개발)

```bash
# bert에서 코드 작성 후
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# .env 채우기 (NEST_TOKEN 등)
.venv/bin/uvicorn main:app --port 8001 --reload
```

MongoDB:
```bash
brew tap mongodb/brew && brew install mongodb-community
brew services start mongodb-community
```

## 배포 (chocolat 영구화)

```bash
# bert → chocolat 코드 동기화
rsync -avh --exclude='.venv/' --exclude='__pycache__/' \
  backend/ chocolat:~/projects/oracle/backend/

# chocolat 측 setup (한 번)
ssh chocolat
cd ~/projects/oracle/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# .env 작성 (NEST_BASE_URL=http://localhost:7780 등)

# LaunchAgent 3개 등록
cp deploy/*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/h59.oracle.backend.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/h59.oracle.midnight.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/h59.oracle.mongo-backup.plist
```

## API (요약)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/ingest` | 캡처 인입 (file/audio/video/comment/model). `async_mode=1`이면 stub 즉시 반환(status=processing) + 백그라운드 처리 |
| GET | `/records` | 최근 Record (paginated) |
| GET | `/records/<id>` | Record 단건 (비동기 완료 폴링·참조 카드) |
| POST | `/chat` | 대화 한 턴 → user/assistant 메시지 쌍 (저장됨) |
| GET | `/chat/history` | 대화 메시지 목록 (타임라인 merge용) |
| GET | `/photos/<vault-rel>` | 사진 서빙 |
| POST | `/records/<id>/reaction` | 이모지 반응 (interesting/useful/skip) |
| PATCH | `/records/<id>` | 코멘트 정정 (Mongo만, vault는 append-only) |
| POST | `/digest/run` | 수동 자정 배치 (target_date 옵션) |
| POST | `/journal/weekly` · `/journal/monthly` | 주/월 회고 수동 트리거 |
| GET | `/journal/list` · `/journal/<jid>` | 일/주/월 저널 목록·본문 (Mongo) |
| GET | `/digest/list` · `/digest/<date>` | 일 저널 파일 목록·본문 (vault) |
| GET | `/index/master` · `/index/meta` | 상위 인덱스 (vault md + Mongo) |
| GET | `/threads` · `/threads/<id>` · `/threads/silent` | thread 조회·펜딩 점검 |
| POST | `/query` | 자연어 검색·질의 → 답변 + 참조 record_id |
| POST | `/embed/backfill` | 임베딩 없는 record 일괄 임베딩 (ORACLE_EMBED 필요) |
| GET | `/llm/models` | Nest 등록 모델·council (폰 picker) |

## 정본·캐시·자동화

- `corpus/YYYY/MM/DD.md` — 정본 평문, 사람도 grep/Obsidian으로 직접 읽기 가능
- MongoDB `oracle.records` — Record 메타·thread/tag/type 부착
- MongoDB `oracle.index_meta` — 월별 통계 (검색 진입점)
- MongoDB `oracle.conversations` — 대화 모드 메시지
- MongoDB 주간 백업 → `~/data/backups/oracle-mongo/` (자동 4주 회전)
- **vault 일일 백업** → `~/data/backups/oracle-vault/YYYY-MM-DD/` (rsync 하드링크 증분, 14일 보관)
- 매일 00:05 자정 배치, 03:20 vault 백업, 매주 일 03:00 mongo 백업 — 전부 자동

## 상태

✅ Layer 1~3 작동 + 메모리 M1~M4(일/주/월 저널 + 3요소 검색 + 워킹메모리) + 비동기 인입 + 대화 모드 + chocolat 영구화 + GitHub public.

⚠️ 보안 전제: 기본 무인증(LAN/tailnet 안에서만 노출 가정), 통신은 Tailscale(WireGuard) 위 HTTP.
`ORACLE_TOKEN` 설정 시 토큰 인증 활성(loopback 면제) — 앱도 `--dart-define=ORACLE_TOKEN=...`으로 빌드.
임베딩 검색은 `ORACLE_EMBED` 설정 + venv numpy 설치 시 활성 (미설정이면 최근순 fallback).
