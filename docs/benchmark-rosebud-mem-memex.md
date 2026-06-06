# Rosebud · Mem.ai · Memex 심층 분석 — Oracle 벤치마킹

> **작성일**: 2026-06-04
> **방법론**: 웹 리서치(5개 각도 fan-out → 21개 소스 → 104개 클레임 → 25개 적대적 검증, **22 confirmed / 3 killed**) + Memex 레포 직접 clone(HEAD `8fcff7d`, 2024-07-25) 코드 분석.
> **전제**: Oracle = Flutter + FastAPI + MongoDB. 사진/메모 캡처 → LLM 즉답 인사이트 + 자정 다이제스트(cron 배치, `backend/digest.py`) + 자연어 검색/질의. **개인용, 과금 없음.**
> 가격·기능 수치는 2026-06 1차 벤더 페이지 기준이며 SaaS 특성상 변동 잦음.

---

## TL;DR

세 서비스는 Oracle의 핵심 루프(**캡처 → 즉답 인사이트 → 배치 다이제스트 → 자연어 질의**)와 각기 다른 축에서 정렬된다.

- **Rosebud** = Oracle의 **Layer 1(실시간 피드백) + Layer 3(자정 다이제스트)를 그대로 제품화**한 가장 가까운 선례. "주간 리포트 + 액션 플랜"이 자정 다이제스트의 진화형.
- **Mem.ai** = **AI 비용을 사용량 한도로 게이팅**하는 모델의 교과서. 무료 월 25개(노트/채팅/PDF) → 무제한 유료.
- **Memex** = 유일한 오픈소스라 **코드 레벨 교훈**이 나온 사례. 핵심은 **Storex(DB-비종속 스토리지 추상화)** 와 **선언적 full-text 인덱스**. 단, 순수 로컬-퍼스트가 아니라 클라우드 하이브리드이고 **AI 코드는 비공개**.

---

## 1. 서비스별 분석

### 🌹 Rosebud (rosebud.app) — AI 저널링

| 축 | 내용 |
|---|---|
| **컨셉/타겟** | 대화형 AI 저널링. 셀프케어·자기이해를 원하는 일반 사용자. (2025년 $6M 펀딩) |
| **핵심 기능** | ① 저널 입력 중·후 **실시간 AI 피드백**("dig deeper") ② **주간 in-depth 리포트** + 패턴 인식 ③ 개인화 **"액션 플랜"** ④ 음성 저널링·**콜 모드** ⑤ 장기 기억 |
| **AI 통합** | 클로즈드소스라 구현 미검증. 다중턴 대화 + 누적 엔트리 배치 분석. "장기 기억"이 임베딩 vs 컨텍스트 주입인지 불명 → **부록 A 참고** |
| **데이터/프라이버시** | 클라우드. 코드 검증 불가 |
| **BM/가격** | freemium + **단일 티어 Bloom $12.99/월**(연 $107.99). **핵심 AI(장기 기억·대화 질의 'Ask Rosebud'·콜 모드·음성)를 Bloom 게이팅**. 무료 = dig deeper·자동 태깅·주간 리포트·하루 2 프롬프트 |
| **UX** | 채팅형 저널. 실시간 가이드 → 주간 회고 → 액션 플랜의 시간 리듬 |

**→ Oracle 직결**: Layer 1(캡처→즉답)과 Layer 3(`digest.py`의 자정 cron 배치)가 Rosebud의 "실시간 피드백 + 주간 리포트"와 개념적으로 동형. 차이는 **모달리티(사진/메모 vs 텍스트/음성 대화)와 주기(일 vs 주)**. "액션 플랜 생성"은 Oracle 다이제스트가 차용할 다음 단계.

출처: [rosebud.app](https://www.rosebud.app/) · [공식 가격](https://help.rosebud.app/getting-started/pricing) · [TechCrunch 펀딩](https://techcrunch.com/2025/06/04/rosebud-lands-6m-to-scale-its-interactive-ai-journaling-app/)

### 📝 Mem.ai (mem.ai) — AI 노트테이킹

| 축 | 내용 |
|---|---|
| **컨셉/타겟** | AI 자동정리 노트. 지식근로자·생산성 사용자 |
| **핵심 기능** | 노트 + AI 채팅 + **딥서치(deep search)** + PDF 이해 + 컬렉션/템플릿 + 미팅 브리프(베타) |
| **AI 통합** | 클로즈드소스. **AI 모델 선택** 제공(유료). "딥서치"가 임베딩 기반인지 불명 → **부록 A 참고** |
| **BM/가격** | **무료 = 월 25개 한도**(노트 25 / 채팅 25 / **PDF 25페이지**) → **Mem Pro $12/월**(연 20%↓)에서 무제한 + 모델 선택 |
| **UX** | 노트 작성 → AI 자동 태깅/연결 → 채팅 질의 |

**→ Oracle 직결**: **LLM 호출 단위(채팅/딥서치/PDF페이지)로 한도를 긋는 사용량 기반 구조** — Oracle은 과금을 안 하지만, 이 한도 설계는 "어디서 LLM 비용이 터지는지"의 신호로 읽을 수 있음(§3 비용 참고).

출처: [get.mem.ai/pricing](https://get.mem.ai/pricing)

### 🌐 Memex (WorldBrain) — 오픈소스 웹 메모리/어노테이션

| 축 | 내용 |
|---|---|
| **컨셉/타겟** | "**Save-summarize-reuse**" — 읽은 웹 콘텐츠를 저장·요약·재사용. 리서처·헤비 리더 |
| **핵심 기능** | 웹/PDF/**YouTube**/소셜 하이라이트+노트 · **full-text 검색**(시간·도메인·리스트·태그 패싯 필터) · **문장/이미지/타임스탬프 참조가 달린 AI 요약·채팅** |
| **AI 통합** | **OpenRouter 게이트웨이 → Google/OpenAI**. 노트/하이라이트를 제공자로 전송, **"제3자 모델 일반학습 미사용" 명시**. ⚠️ **AI 코드는 오픈소스 레포에 없음**(비공개 백엔드) |
| **데이터/프라이버시** | **하이브리드**: 로컬-퍼스트(Dexie/IndexedDB) **+ Supabase 클라우드** 동기화/저장. 순수 로컬-온리 아님 |
| **BM/가격** | **크레딧 기반**: Starter $5/월(12,000 크레딧) · All-you-can-read $10/월(60,000) · 무료 100 크레딧 · 라이프타임 $450 |
| **기술 스택** | TypeScript 93.3% · React 17 RC + Redux · Webpack 4 · Chrome/Firefox 확장 |

출처: [memex.garden/privacy](https://memex.garden/privacy/) · [memex.garden/pricing](https://memex.garden/pricing) · [Chrome 웹스토어](https://chromewebstore.google.com/detail/memex/abkfbakhjpmblaafnpgjppbmioombali) · [GitHub](https://github.com/WorldBrain/Memex)

---

## 2. Memex 코드 심층 — 코드 분석 ↔ 웹 리서치 대조

레포 직접 clone(HEAD `8fcff7d`, master)과 웹 리서치(현행 제품)를 교차하니 **오픈소스 코드와 현행 제품 사이의 시차**가 드러난다.

| 항목 | 📦 오픈소스 코드(HEAD `8fcff7d`) | 🌐 현행 제품(privacy/마케팅) | 해석 |
|---|---|---|---|
| **클라우드 백엔드** | **Firestore**(`firebase` 10.11, `storex-backend-firestore`) | **Supabase** | 제품은 Supabase로 마이그레이션, **오픈소스 코드엔 Firestore 잔재** → 공개 레포가 제품보다 뒤처짐 |
| **AI 경로** | `summarization-llm` → **Cloudflare Worker** → OpenAI **gpt-4o** | **OpenRouter** → Google/OpenAI | 둘 다 "클라이언트 직접 호출 안 함, **프록시 경유**"로 일치. Worker가 OpenRouter를 부르거나 시점차 |
| **AI 핵심 로직** | 프롬프트/RAG는 **private submodule `memex-common`** | 비공개 백엔드 | **양쪽 다 코드 미확인** — AI 구현은 끝내 블랙박스 |

### 2.1 코드 레벨 발견 (직접 clone, 확인됨)

**(a) 아키텍처** — git submodule 기반 의사 모노레포. webpack 4 멀티 엔트리(background / popup / options + 콘텐츠 스크립트 6개). 도메인 수직 분할(`search`, `annotations`, `page-indexing`, `personal-cloud`, `summarization-llm`, `in-page-ui`…). 자체 RPC 레이어(`util/webextensionRPC`: `makeRemotelyCallable` + `RemoteEventEmitter.emitToTab`).

**(b) 데이터 모델 & 검색** ⭐ — IndexedDB ← Dexie 4 ← **storex 추상화** 3층(`src/search/storex.ts`). Page 모델 PK = 정규화 URL, 본문을 **사전 토큰화**해 `terms`/`urlTerms`/`titleTerms` 배열로 저장(`search/models/page.ts:42-51`). **full-text 검색 = 외부 엔진 없이 IndexedDB `multiEntry` 인덱스(`*${field}`)로 자체 역색인.** 쿼리 진입점 `unifiedSearch`가 3분기: ① 빈 검색=시간 역순 타임라인(빈 날 do-while 스킵, `unifiedBlankSearch`) ② 리스트 필터 ③ 텀 검색(`splitQueryIntoTerms`로 필드 스코프·구문·fuzzy 파싱).

**(c) 동기화 & 암호화** — 두 시스템 공존. 현행 "Personal Cloud"(change-watcher 미들웨어 → `ActionQueue` → Firestore, push/pull 뮤텍스 — **E2E 암호화 코드 안 보임**). 레거시 P2P(WebRTC `simple-peer` + **NaCl secretbox E2E** `TweetNaclSyncEncryption`).

**(d) AI** — 클라이언트가 LLM 직접 호출 안 함. `summarization-llm/background/index.ts` → **Cloudflare Worker 프록시** → OpenAI gpt-4o/gpt-4o-mini. **BYO 키 이중모드**(`AIActionAllowed`/`COUNTER_STORAGE_KEY`로 사용량 카운터). **토큰 스트리밍**(`queryAI` async generator → `emitToTab('newSummaryToken')`) + chatId별 **취소 핸들**(`ongoingRequests` Map). 로컬-퍼스트 시맨틱 검색("Rabbit Hole")은 별도 로컬 데스크톱 HTTP 서버에 `PUT /add_page` 색인 / `POST /get_similar` 검색.

**(e) 익스텐션** — MV2/MV3 동시 지원. MV3 service worker 한계 대응(`xhr-shim`, `linkedom/worker`, `keepWorkerAlive`). In-page 주석 앵커링 = **W3C 스타일**(`dom-anchor-text-quote/position` + `approx-string-match`로 본문 변경 시 퍼지 재앵커링).

### 2.2 웹 리서치가 새로 입증한 아키텍처 (코드 분석 보강)

- **Storex = DB-비종속 스토리지 추상화 계층**. 단일 추상화로 **3개 백엔드 플러그인**: Dexie(IndexedDB/오프라인), **Sequelize(서버 SQL: PG/MySQL/SQLite)**, Firestore(mBaaS). "Memex 스토리지로 출발해 **프로덕션 3년+ 가동**" ([storex](https://github.com/WorldBrain/storex))
- **공유 스키마 패키지** `@worldbrain/memex-storage` — **브라우저 확장과 모바일 앱이 동일 스키마 재사용** ([memex-storage](https://github.com/WorldBrain/memex-storage))
- **선언적 full-text 인덱스**: `pages` 컬렉션에 `text→terms`, `fullTitle→titleTerms`, `fullUrl→urlTerms`. storex-backend-dexie가 이를 IndexedDB MultiEntry 인덱스로 변환, **stemmer 강제**(`_validateRegistry`)
- **모바일은 SQLite + TypeORM**(`storex-backend-typeorm`) — 동일 추상화 위에 **백엔드만 교체**한 실증 ([Memex-Mobile](https://github.com/WorldBrain/Memex-Mobile))

> ⚠️ memex-storage(v0.1.1)·storex-backend-sequelize는 **휴면 상태** — "공유 스키마·3-백엔드"는 **역사적·구조적 사실**이나 "현재도 활발히 재사용 중"은 낙관적 표현.

---

## 3. Oracle 시사점 (우선순위순)

### 🟢 즉시 적용 가치 높음

1. **AI 호출은 FastAPI 프록시 경유 + BYO 키 이중모드 + 사용량 카운터** — 세 서비스 + Memex 코드가 **만장일치** 패턴. 클라이언트(Flutter)에 LLM 키 안 박음, 키 보호·모델 교체·레이트리밋·(개인용이면) 사용량 관측을 백엔드 한 곳에서. Memex: "사용자 OpenAI 키 있으면 그걸 쓰고 없으면 서버 크레딧 차감".

2. **토큰 스트리밍 + 캡처 단위 취소 핸들**(Memex `queryAI` async generator + `ongoingRequests` Map). "즉답 인사이트"의 체감 지연 ↓, 새 캡처 오면 이전 추론 무효화 — 채팅 동반자 UX에 그대로 매핑. FastAPI는 SSE/WebSocket, Flutter는 캡처 단위 취소 토큰.

### 💰 비용 (과금 없음 → 본인 LLM 비용 최적화)

Oracle은 개인용·무과금이므로 세 서비스의 유료벽은 **수익화 모델이 아니라 "어디서 LLM 비용이 터지는지"의 신호**로 읽는다.

- 세 서비스 공통: **대화형 질의·딥서치·무제한 채팅**을 유료/크레딧 뒤에 둠 = 이게 가장 비싼 호출. Oracle도 자연어 질의·다이제스트가 비용 핫스팟.
- **자정 다이제스트(`digest.py`, 매일 전체 캡처 배치 LLM 호출)가 최대 비용원.** 최적화 방향:
  - **증분 처리**: 전체 재요약 대신 그날 신규 캡처만 처리하고 누적 요약에 머지.
  - **모델 티어링**: 즉답 인사이트는 저렴/빠른 모델(gpt-4o-mini 급), 다이제스트·심층 질의만 상위 모델.
  - **캐싱**: 동일/유사 캡처에 대한 인사이트 재사용, 프롬프트 캐싱 활용.
  - **로컬 우선**: Oracle은 이미 LLM picker가 로컬 우선 — 일상 캡처 인사이트를 로컬 모델로 처리하면 비용 0에 수렴.

### 🟡 검색·데이터 설계

3. **자연어 쿼리 사전 파싱** — 날짜·태그·**위치(Oracle EXIF GPS 보유)** 같은 구조적 조건은 파서로 뽑아 Mongo 필터로 내리고, 의미 검색만 임베딩에 위임. Memex는 필드 스코프(`inTitle/inContent`)+구문+`chrono` 날짜 파싱 + 시간/도메인/태그 패싯 필터.

4. **"빈 검색 = 시간 역순 타임라인, 빈 날 스킵"**(Memex `unifiedBlankSearch`). Oracle 자정 다이제스트 + 인덱스 뷰가 정확히 이 패턴. Mongo `capturedAt` 인덱스로 구현.

5. **시맨틱 검색을 `add`/`get_similar` 2개 엔드포인트로 분리**(Memex "Rabbit Hole"). 임베딩/벡터스토어 교체 용이 — Atlas Vector Search로 이 인터페이스 구현.

6. **공유 스키마 + `schemaVersion` 버전 변환**(Storex/memex-storage 패턴). Flutter↔FastAPI가 스키마를 단일 정의로 공유하고 문서에 `schemaVersion`을 둬 캡처 포맷·LLM 결과 구조 진화에 대비.

### 🔴 안티패턴 — 따라하지 말 것

7. **Memex의 stemmer/CJK 음절 분해 토크나이저는 한국어에 부적합**. `processCJKCharacters`가 한글을 음절 단위로 색인 → 정밀도 낮음. Oracle은 **임베딩 기반 의미 검색 + 형태소/구조 필터** 하이브리드로 가야 함 → **부록 B 참고**.

---

## 4. 신뢰도 & 한계

- ✅ **강한 근거**: 가격·기능(1차 벤더 페이지) · Memex 코드 구조(직접 clone + 4개 공개 레포 교차검증).
- ⚠️ **검증 불가**: **Memex AI 구현**(요약·채팅·타임스탬프 참조 생성)은 비공개 백엔드/`memex-common`(private)이라 코드 레벨 분석 **불가능**. Rosebud·Mem.ai는 클로즈드소스라 **기능 "존재"만 검증, "구현 방식·효능"은 미검증**.
- ❌ **기각된 클레임 3건**: Memex 다중 LLM/BYO-model/MCP(memexlab.ai와 혼동, 1-2) · 순수 offline-first(1-2) · "AI 라이브러리 없음→LLM 비종속"(0-3).
- ⏰ 가격은 2026-06 기준.

---

## 부록 A — 임베딩 vs 컨텍스트 주입

> "장기 기억"/"딥서치"가 둘 중 무엇인가에 대한 답. **둘 다 결국 LLM 프롬프트에 텍스트를 넣는 것**이고, 차이는 **무엇을 넣을지 고르는 방법**과 **확장성**이다.

### 컨텍스트 주입 (context injection / stuffing)
관련될 만한 데이터를 **통째로(또는 단순 규칙 필터로)** 프롬프트에 다 넣음.
- 예: "최근 7일 캡처 전부" 또는 "이 사용자의 모든 노트"를 붙여 "이걸 기반으로 답해줘".
- **장점**: 구현 단순, 별도 인프라(벡터DB) 불필요. 데이터가 작으면 정확도 최고(다 보니까).
- **단점**: 컨텍스트 윈도우 한계 → 데이터 많아지면 못 넣음. 토큰 비용이 데이터에 비례해 폭증(매번 전체). 무관한 내용이 노이즈("lost in the middle").

### 임베딩 기반 검색 (embedding / vector search / RAG)
모든 데이터를 미리 **임베딩 벡터**(의미를 담은 고차원 숫자 배열, 예 1536차원)로 변환해 벡터DB에 저장. 질의도 벡터로 변환 → **코사인 유사도**로 가장 가까운 상위 K개만 검색 → **그 K개만** 프롬프트에 주입.
- **장점**: 데이터가 수만~수백만이어도 관련 소수만 넣으니 **확장 가능**, 토큰 비용 일정. 키워드가 안 겹쳐도 **의미**로 찾음("강아지" 질의 → "반려견" 노트 매칭).
- **단점**: 임베딩 파이프라인·벡터DB 필요. "가까운" 걸 가져올 뿐 정답 보장은 아님. 청킹(chunk) 전략 필요.

### 비유
- 컨텍스트 주입 = **책 전체를 통째로 읽고 답하기** (짧으면 OK, 백과사전이면 불가능)
- 임베딩 검색 = **색인에서 관련 페이지만 찾아 그 페이지만 읽고 답하기**

### 하이브리드 (실무 표준)
실제로는 섞는다: 임베딩으로 후보를 추리고(retrieval) + 최근 항목 몇 개는 무조건 주입(recency) + 날짜/태그 구조 필터로 범위 축소.

### Oracle 함의
- 사용자 추측("컨텍스트 주입")은 **합리적** — 저널/노트 앱은 사용자당 데이터가 그리 크지 않아 초기엔 컨텍스트 주입으로 충분한 경우가 많다.
- **자정 다이제스트**는 "그날치"만 보면 되므로 **컨텍스트 주입이 자연스럽고 비용도 통제됨**(하루 분량은 작음).
- **자연어 검색/질의**는 전체 누적 캡처가 대상 → 데이터가 쌓이면 컨텍스트 주입은 한계. **이 부분만 임베딩 검색이 유리.**
- 결론: **다이제스트=컨텍스트 주입, 전역 질의=임베딩** 으로 나누는 게 Oracle에 맞는 분담.

---

## 부록 B — 한국어 full-text 검색 토크나이저 (상세)

> Memex식 토크나이저가 왜 한국어에 부적합하고, Oracle은 무엇을 써야 하는가.

### 왜 문제인가 — 한국어는 교착어
한국어는 **어간 + 조사/어미**가 붙는다. "학교**에서**", "학교**를**", "학교**는**" → 핵심은 모두 "학교". **공백 split만 하면 셋이 다른 토큰**이 되어 "학교"로 검색해도 안 잡힌다. full-text 검색의 첫 단계인 **토크나이징(텍스트를 검색 단위로 쪼개기)** 이 한국어에선 영어처럼 단순하지 않다.

### Memex 방식 = CJK 음절 분해 (안티패턴)
`processCJKCharacters`가 한글을 **음절(글자) 단위로 분해**: "학교에서" → "학","교","에","서".
- "학"+"교"가 연속한 문서를 부분 매칭으로 잡을 수는 있으나,
- **정밀도가 낮다**: "학"·"교"가 흩어진 무관 문서도 매칭, 의미 단위가 깨져 랭킹 품질 저하, 짧은 질의에서 노이즈 큼.
- 한자(중국어)·가나(일본어)는 글자 한 개가 의미 단위라 그나마 통하지만, **한국어엔 부적합**.

### 올바른 옵션 3가지
1. **형태소 분석기 (morphological analyzer)** — "학교에서" → "학교"(명사)+"에서"(조사)로 분석해 명사/어간만 색인.
   - 도구: 은전한닢(mecab-ko), Khaiii(카카오), Okt(Open Korean Text), Komoran 등.
   - 검색엔진 표준: **Elasticsearch/OpenSearch의 Nori 플러그인**(mecab-ko 기반).
   - 장점: 높은 정밀도. 단점: 사전 관리, 신조어/오타에 약함.
2. **n-gram (bigram)** — 사전 없이 2글자씩 슬라이딩: "학교에서" → "학교","교에","에서".
   - 장점: 사전 불필요, 신조어·고유명사 강건. 단점: 색인 큼, 정밀도 중간. (Memex의 unigram 음절 분해보다 한국어에 나음.)
3. **임베딩 기반 의미 검색** — 토크나이징 자체를 우회. 한국어 지원 임베딩 모델(OpenAI `text-embedding-3`, Cohere multilingual, KoSimCSE/ko-sroberta 등)로 벡터화 → 조사 변형에 강건. 단점: 정확한 키워드(고유명사·숫자) 매칭엔 약할 수 있음.

### Oracle 권고 (MongoDB 기반)
- **주의**: MongoDB 기본 text index는 **한국어 형태소 분석을 지원 안 함**(언어별 stemmer에 korean 없음) → Mongo text search만으론 한국어 품질 떨어짐.
- **권장 조합**:
  - **의미 검색** = MongoDB **Atlas Vector Search + 한국어 지원 임베딩 모델**. (이미 LLM을 쓰니 임베딩 추가가 자연스러움.) "자연어 질의"에 최적.
  - **정확 매칭/필터** = 날짜·태그·**위치(GPS)** 는 구조적 필드 인덱스로 처리(형태소 무관).
  - 키워드 검색이 더 필요하면 **Atlas Search + Nori 애널라이저**(Atlas Search는 Lucene 기반이라 nori 지원) 또는 별도 형태소 전처리.
- **결론**: Memex식 클라이언트 토크나이저를 베끼지 말고, **임베딩(의미) + 구조적 필터(정확)** 하이브리드로 — §3-3·5·7과 연결.

---

## 소스 (주요)

**1차(벤더/레포)**: rosebud.app · help.rosebud.app/getting-started/pricing · get.mem.ai/pricing · memex.garden/privacy · memex.garden/pricing · github.com/WorldBrain/{Memex, memex-storage, storex, storex-backend-dexie, Memex-Mobile}
**2차/검증**: TechCrunch(Rosebud 펀딩) · Chrome 웹스토어/Firefox 애드온 · Medium(Storex 소개)
