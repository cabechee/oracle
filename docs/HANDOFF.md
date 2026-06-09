# Oracle 핸드오프 — 2026-06-07 2차 세션

> **목적**: 다음 세션이 바로 이어가도록 이번 세션의 **구현·리팩토링·중단된 코드 감사 발견**을 정리.
> 확정 설계 원문 = [`docs/research/`](./research/) (memory-hierarchy · photo-pipeline · prompt-caching) + [`docs/benchmark-rosebud-mem-memex.md`](./benchmark-rosebud-mem-memex.md). 1차 세션(같은 날 오전) 기록은 git log + auto-memory.
> **다음 세션은 이 문서부터 읽고 시작할 것.**

---

## 0. 위치 (한눈에)

- **Oracle** = 개인 일상 디스커버리 채팅 동반자 + 비서. Flutter + FastAPI + MongoDB + Nest(별도 repo `~/projects/nest`).
- oracle HEAD = 이 핸드오프 커밋. **origin/main(`b92308d`)보다 ahead 13 — 전부 미push** (push 여부 = 사용자 결정. repo는 public!).
- **chocolat 배포 = 최신**(리팩토링 포함) 라이브 작동 중. 폰(Z Fold7) = 최신 debug APK 설치됨.
- Flutter **3.44.1 / Dart 3.12.1** (이번 세션 업그레이드), record **7.0.0**.

## 1. 이번 세션에서 한 일 (커밋 순)

| 커밋 | 내용 |
|---|---|
| `dc84202` | **Flutter 사진 3단계 표시** — Record에 analysis/suggestion + 💡제안 버블 + 🔍분석 펼치기 |
| `2cf953a` | **메모리 M1~M4** — 서술 저널(일/주/월) + 3요소 검색 + 워킹30일 (아래 3장) |
| `cf75105` | **Phase 1: Flutter/Dart 3.12 + record 7.x** — APK 빌드 복구(record_linux 0.7.2가 최신 platform_interface 미구현으로 **클린 빌드가 안 되던 기존 버그**) |
| `871e242` | **Phase 2: Flutter 모듈화** — main.dart 1478→5줄 (아래 2장 구조) |
| `e2743cc` | **Phase 3: 백엔드 모듈화** — digest.py(737)·api.py(313) 분해 (아래 2장) |
| `2f78ac6` | 분석 카드 견고화 — 스키마 외 키도 렌더(system-drop으로 즉흥 JSON 와도 표시) |
| `0912f63` | 전송 시 "전송됨" 토스트 |
| `d6eabea`+`04fe3a3` | **사진 첫 탭 안 찍히던 버그 해결** — 콜드 스타트 시 카메라 init(~2-3s) 전 첫 탭이 무시됨 → 버튼 항상 활성 + capture()가 준비 최대 4s 대기(+1회 재시도) |

- **M5(6개월 미디어 age-out) = 사용자가 스킵.** M6(Nest 캐싱) = Nest repo에서 시도했다가 **사용자 지시로 전부 원복** — Nest는 별도 repo, oracle 세션에서 건드리지 말 것(auto-memory `nest-separate-repo` 참조).
- 폰 검증 완료: 모듈화 빌드 정상 실행, 히스토리 탭에서 🔍분석 카드 렌더 확인.

## 2. 새 코드 구조 (리팩토링 후) ⭐ 구 문서의 digest.py/api.py/main.dart 언급은 전부 구식

**Flutter** (`app/lib/`): 통신 규칙 = 위젯→컨트롤러(메서드) → RecordStore(SSOT) → ListenableBuilder 리빌드. 네트워크는 `api.dart`만. capture/chat은 서로 모르고 store로만 만남.
```
main.dart(5줄) · app.dart(테마/루트)
core/record_store.dart        # records+pendings SSOT (ChangeNotifier)
features/capture/  capture_controller.dart(카메라·영상·오디오·갤러리·공유·ingest) + record_tab.dart
features/chat/     chat_controller.dart(로딩·리액션·편집) + chat_list.dart + record_bubble.dart(+제안/분석) + pending_bubble.dart + digest_preview_card.dart
features/home/     home_page.dart(셸·생명주기·탭·모델선택) + home_tab.dart
features/notifications/ notif_service.dart
(루트에 남음: api/applog/models + digest·index·query·onboarding·llm_picker 화면 — screens/ 이동은 미실행, 동작 무관)
```

**Backend** (`backend/`): 규칙 = api 라우터(얇음)→서비스→agent→인프라 **단방향**.
```
api/               # 도메인 라우터: ingest·records·journal·threads·query·index·nest (+__init__ include, 22라우트)
ingest.py          # 캡처 파이프라인 (Layer 1)
nightly.py         # 자정 오케스트레이션 (run_nightly: 일 + 월요일주간 + 1일월간 / run_daily)
classify.py        # thread_judge + type_classify
journal.py         # 일/주/월 서술 저널 생성·저장·조회 (구 digest 프롬프트 포함)
index.py           # 상위 인덱스 (master.md + index_meta)
nightly_common.py  # 공유 헬퍼 (records_brief·resolve_alias·parse_json_safe)
query.py           # 자연어 질의 (memory.search 사용)
agent/             # llm.py(Nest 래퍼+cache_prefix hook) · vision.py(사진3단계) · memory.py(3요소 검색+워킹메모리)
인프라: nest_client · db(journals 컬렉션 추가) · corpus · embedding · config · threads
```

## 3. 메모리 시스템 (M1~M4) — 구현 완료, ⚠️ **라이브에서 임베딩 꺼져 있음**

구현: 일 다이제스트→**시간순 서술 일기**(`journals` kind=day, vault `digest/*.md` 그대로) · 주/월 회고(`journal/*.md` + journals week/month, 자정 cron이 월요일/1일 자동) · `agent/memory.py` 3요소 검색(유사도+recency지수감쇠+importance[reaction], 저널+record 합집합, min-max 정규화, `config.MEMORY_W_*`) · 워킹메모리(지난 ~29일 일기+오늘 raw)를 모든 인사이트에 주입(`ORACLE_WORKING_DAYS=30`).

**라이브 확인 결과 (chocolat ssh, 2026-06-07 저녁)**:
- `.env`에 **`ORACLE_EMBED` 없음** → records 21개 중 임베딩 0, journals(day-2026-06-07·week-2026-W23) 임베딩 false. **3요소 검색이 잠자는 상태**(graceful fallback=최근순+최근저널). 
- chocolat venv에 **numpy 없음** → ORACLE_EMBED 설정해도 검색 불가(이중 비활성).
- PIL은 **있음**(11.3.0) → EXIF GPS 라이브 작동 가능 (구 핸드오프의 "Pillow 미설치"는 bert dev venv 얘기였음).

**활성화 절차** (다음 세션 최우선 후보):
1. Nest에 임베딩 모델 등록 (provider openai|openai_compat, `/api/embed` 지원 — nest `94e737a` 구현돼 있음)
2. chocolat `~/projects/oracle/.env`에 `ORACLE_EMBED=<alias>` 추가
3. `ssh chocolat '~/projects/oracle/backend/.venv/bin/pip install numpy'` + backend 재시작
4. `curl -X POST http://localhost:8001/embed/backfill` (record) — 저널은 다음 자정에 자동, 또는 `/digest/run?target_date=`로 재생성

## 4. 🔴 중단된 작업: 전체 코드 감사 (다음 세션이 이어서)

사용자 요청: "소스·문서 다 읽고 → 구현 방식 분석, 의도/구현 갭, 버그, (개인용 기준) 보안 포인트, 개선 제안". **정독+라이브 확인까지 끝났고 종합 리포트 작성 직전에 중단.** 아래가 그때까지의 발견 전부 — 이걸 기반으로 리포트/수정하면 됨.

### 4.1 버그/문제 (확정)
1. ~~`.gitignore`에 `journal/` 누락~~ → **이 핸드오프 커밋에서 수정함** (M4가 만든 주/월 회고 vault 디렉토리가 public repo에 커밋될 수 있었음)
2. **ingest 타임아웃 미스매치**: 앱 `_ingestTimeout=120s`(api.dart) < 사진 3단계 실측 **>150s**(claude CLI 2회+인사이트). 폰은 "전송 실패" 토스트인데 백엔드는 완료 → record가 나중에 나타나는 혼란. **해법 후보**: (a) 타임아웃 300s로 (b) 근본적으로 ingest 비동기화 — 즉시 202+record_id 반환, 완료는 폴링/푸시(추천, 대화모드와 묶어서)
3. **Nest system-drop** (별도 repo 작업): `/api/call`이 `system`을 dispatch로 안 넘김 → CLI(클로드 구독)·openai_compat 경로에서 ANALYZE/REASON_SYSTEM 드롭 → **사진 3단계 라이브 저하 확정**(insight="(코멘트 생성 실패)", suggestion 빈값, analysis가 스키마 아닌 즉흥 키). Nest repo 세션에서: system 전파 + M6 캐싱 + Opus4.8 thinking(`budget_tokens`→adaptive).
4. **dead code**: `config.CONTEXT_MINUTES/MAX`(사용처 없음 — M3가 대체), `ingest.VLM_SYSTEM`(정의만 남음), `embedding.search()`(query가 memory.search로 갈아타서 미사용; embed_record/embed_journal/backfill은 사용 중).

### 4.2 의도 vs 구현 갭
- **"모든 LLM 호출은 agent.llm 단일 통로" 원칙 vs 실제**: vision만 agent.llm 경유. ingest 텍스트 경로·classify·journal·query는 `nest_client.call` 직접 호출. cache_prefix hook(M6 대비)을 살리려면 이들도 agent.llm로 이관 필요(리팩토링 plan의 "이관 예정"이 골격만 됨 — `agent/insight.py`·`agent/chat.py` 미생성).
- **week/month 저널도 임베딩하지만 검색(memory.search)은 kind=day만** — 임베딩 낭비 or 검색 범위 확대, 결정 필요.
- **워킹메모리 30일 주입에 토큰 상한 없음** — 저널 쌓이면 캡처당 수십 KB. M6 캐싱 전까지 비용/지연 증가. (그리고 Nest CLI 경로는 캐싱 불가 — 캐싱 받으려면 anthropic API 모델 등록 필요, research/prompt-caching.md)
- README 디렉토리 트리가 구식(digest.py·api.py 단일 파일 시절). 갱신 필요.

### 4.3 보안 포인트 (완전 개인용 기준)
- **backend(0.0.0.0:8001) 완전 무인증**: 같은 LAN의 누구나 기록/사진/저널 열람, ingest(LLM 비용 발생), digest 트리거, record 수정 가능. 폰은 ts.net(WireGuard 암호화)으로 접속하니 **권장: Nest처럼 토큰 헤더 1개 추가** 또는 Tailscale 인터페이스에만 바인딩. (photos 경로는 path traversal 방어 돼 있음 — realpath 체크 확인됨.)
- **corpus vault(정본!) 백업 없음** — Mongo만 주간 백업(backup-mongo.sh). 사진+평문 마크다운이 chocolat 디스크 단일 사본. **권장: vault rsync/restic 백업 cron — 사실상 최우선 개선.**
- public repo에 tailnet 호스트명 노출(api.dart 기본 baseUrl) — Tailscale 인증 필요라 직접 위험 낮음, 인지만.
- `usesCleartextTraffic=true` + HTTP — Tailscale 위라 실질 암호화. LAN 직접 접속 경로만 평문. 개인용 수용 가능.
- 시크릿 위생 양호: .env gitignored, 토큰 하드코딩 없음, 폰에 Nest 토큰 미노출(backend가 중계).

### 4.4 개선 후보 (우선순위 제안)
1. **임베딩 활성화** (3장 절차 — 메모리 시스템이 실제로 살아남)
2. **vault 백업 cron**
3. **ingest 비동기화**(+타임아웃) — 대화 모드와 같이 설계 권장
4. backend 토큰 인증
5. dead code 정리 + README/문서 갱신
6. 리액션/편집을 인덱스 대신 record id 기반으로(타이밍 레이스 제거), records 중복 방지(refresh 중 resolvePending 시)
7. agent.llm 이관 완성(insight/chat/classify/journal) — M6 캐싱 전제조건

## 5. 운영 노트
- **배포**: `rsync -avh --exclude='.venv/' --exclude='__pycache__/' backend/ chocolat:projects/oracle/backend/` → `ssh chocolat 'launchctl kickstart -k gui/$(id -u)/h59.oracle.backend'`. 구 api.py·digest.py 잔재는 chocolat에서 제거 완료.
- **폰 빌드/설치**: `JAVA_HOME=/opt/homebrew/opt/openjdk@17 flutter build apk --debug`; adb = `/opt/homebrew/share/android-commandlinetools/platform-tools/adb`. 무선 디버깅 포트는 슬립마다 바뀜(mdns는 Tailscale 안 넘어감) → **사용자에게 IP:PORT 새로 받아야**.
- **⚠️ 폰 화면 타임아웃을 10분(600000ms)으로 바꿔둠**(ADB 자동화용). 복구: `adb shell settings put system screen_off_timeout 30000`(원하는 값으로).
- chocolat에 테스트 record 2건 있음("강아지 (Step1 검증)" rec-20260607-164925-…, 빈 실패분 rec-20260607-164646-…) — 지워도 됨. journals에 day-2026-06-07·week-2026-W23 생성돼 있음(수동 트리거된 것).
- Nest repo는 기존 미커밋 3파일(db.py·seed_registry.py·test_dispatch.py) 그대로 — 내 변경 아님, 사용자 확인 대기.

## 6. 다음 세션 시작점 (우선순위 제안)
1. **감사 마무리** — 4장 발견을 사용자와 정리, 상위 개선 적용(임베딩 활성화 → vault 백업 → ingest 타임아웃/비동기).
2. **대화 모드** — 히스토리 탭 타임라인 + 하단 입력 + `conversations` 컬렉션 + `agent/chat.py`(query 이관). ingest 비동기화와 묶으면 효율적.
3. **(Nest repo 별도 세션)** system 전파 + M6 캐싱 + Opus4.8 thinking — 사진 3단계 품질 직결.
4. **push 결정** (ahead 13, public repo).
