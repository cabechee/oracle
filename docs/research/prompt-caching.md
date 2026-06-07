# Prompt Caching (30일 워킹메모리) — 조사 정리

> 주제: Oracle 30일 롤링 워킹메모리용 prompt caching 경로 조사
> 소스: 4종 리서치 요약(anthropic/gemini/openai/pattern) + Nest 코드 분석 + 검증된 Nest 백엔드 소스 + claude-api skill 레퍼런스(최소 prefix 토큰·TTL 메커니즘·경제성 확인).

---

## TL;DR

30일치(~15–30K 토큰) 고정 프리픽스를 매 캡처마다 주입하는 Oracle의 패턴에는 **Anthropic Claude API + `cache_control`이 유일하게 적합한 경로**다.

- Nest가 현재 쓰는 **gemini CLI(`-p`)로는 캐싱이 사실상 불가**하다.
- OpenAI는 자동 캐싱이라 코드 변경 없이 따라오지만, 30일 프리픽스에 맞는 구조(고정 앞 / 가변 뒤)가 전제다.
- Nest에는 **(1) `call_anthropic`의 content 순서 재배치 + system 블록 도입 + `cache_control`, (2) usage 필드 확장, (3) 자정 keep-warm 프리워밍** 정도의 수정이 필요하다.
- 자정 재구성은 "강제 무효화"가 아니라 "교체만" 하면 되고(읽기가 TTL 무료 갱신), 캡처가 띄엄띄엄이면 TTL 만료가 진짜 문제이므로 `ttl:"1h"` + keep-warm으로 대응한다.

---

## 경로 비교 (Claude API `cache_control` / Gemini `cachedContent` / OpenAI 자동)

세 제공자 비교:

| 경로 | 30일 고정 프리픽스 적합성 | 판정 |
|---|---|---|
| **Claude API `cache_control`** | 명시적·결정론적 prefix 캐싱. 30K ≫ 최소 prefix(Opus 4.8/Sonnet 4.6 = 1,024, Opus 4.7/4.6/Haiku 4.5 = 4,096). 첫 요청만 write(1.25×/2×), 이후 read(0.1×) → ~90% 절감. usage로 검증 가능. | ✅ **최적** |
| Gemini `cachedContent` API | guaranteed discount + TTL 제어 가능하나 **CLI에 없고 SDK(API 키) 필수**. 인증 모델 전환 비용. | △ 가능하나 비용 큼 |
| OpenAI 자동 캐싱 | opt-in 불필요, prefix만 같으면 자동(1024+ 토큰, 128 increment). 단 제어/관측 수단이 코드에 없고, 인메모리 5~10분 후 소멸. | ○ 따라오지만 제어 불가 |

**핵심 이유**: Oracle의 프리픽스는 "같은 날 안에서 byte-identical하게 고정"되는 전형적 캐싱 대상이다. Claude만이

- (a) breakpoint를 코드에서 명시 배치하고,
- (b) `ttl:"1h"`로 띄엄띄엄 트래픽에 대응하고,
- (c) `cache_read_input_tokens`로 hit률을 관측할 수 있다.

따라서 **즉답 인사이트의 주 모델을 Claude API(anthropic provider)로 두고 거기에 캐싱을 적용**하는 것이 정답이다.

> **주의 (모델별 차이)**: 모델별 최소 prefix가 다르다. 30K는 모든 현행 모델을 상회하므로 무난하지만, **Opus 4.7/4.6로 전환 시 임계값이 4,096**이라는 점만 기억하면 된다(30K는 여기서도 통과). 또한 Opus 4.8/4.7은 thinking이 adaptive 전용이고 `budget_tokens`가 제거되어 400을 낸다 → 현 `call_anthropic`의 extended-thinking 분기(110–113행 `thinking={"type":"enabled","budget_tokens":...}`)는 **Opus 4.8/4.7에서 그대로 쓰면 에러**다. 이건 캐싱과 별개의 선결 이슈이므로 아래 Nest 코드 수정점과 구현 단계에서 함께 짚는다.

---

## gemini CLI 캐싱 가능 여부 (결론과 근거)

**결론: CLI(`-p`)로는 불가. API provider 추가가 필수.**

근거:

- `cli_backend.py`의 `call_gemini`(150–176행)는 `gemini -p <prompt> -o text -y --skip-trust ...`(165행)를 subprocess로 호출하는 **구독/로그인 auth 래퍼**다. `cache_control` 같은 캐시 제어 인자가 `-p`에 없다(154행 주석도 effort 플래그조차 없다고 명시).
- gemini-cli의 자동(implicit) 캐싱은 **API 키/Vertex auth에서만** 동작하고 **OAuth(구독 로그인)에서는 미지원**(Code Assist API가 cached content 생성을 지원하지 않음). Nest의 gemini는 `account_env`에서 `HOME`을 옮겨 구독 계정을 쓰는 구조(48–49행)라 정확히 이 미지원 케이스다.
- 설령 API 키 auth라 해도 implicit 캐싱은 *반복 요청 간* prefix 공유로만 이득이 나고, **단발 `-p` 호출엔 보장된 절감이 없다**.

**결론**: Gemini에서 30일 프리픽스 캐싱을 쓰려면 google-genai SDK의 explicit `cachedContent` API 모드(`client.caches.create(...)` → `generate_content(cached_content=...)`)가 필요하고, 이는 **구독 auth → API 키 auth 전환을 수반**한다. fleet 대시보드의 LLM provider 설정과 정합한지 먼저 확인해야 한다.

→ 다만 경로 비교의 결론대로 **Gemini를 캐싱 경로로 승격할 실익이 낮다.** 주 캐싱 경로는 Claude로 가고, Gemini는 캐싱 없는 보조/대안 모델로 유지하는 편이 단순하다.

---

## TTL ↔ 자정 재구성 정합 + 띄엄띄엄 캡처 대응(keep-warm)

### 메커니즘 (확인된 사실)

- TTL: 기본 `ephemeral` = **5분**, `{"type":"ephemeral","ttl":"1h"}` = **1시간**.
- **캐시 읽기는 TTL을 무료로 갱신한다**("refreshed for no additional cost each time the cached content is used"). 즉 TTL보다 짧은 간격으로 계속 요청하면 캐시는 무한히 warm.
- 비용: write 5분 1.25× / 1시간 2.0×, read 0.1×. 손익분기 — 5분 TTL은 2회 요청, 1시간 TTL은 최소 3회 read(2× + 0.2× = 2.2× < 3×).

### 자정 재구성과의 정합성

- 30일 윈도우가 자정에 한 번 바뀌면 **"무효화를 강제"할 필요 없다.** 자정 이후 첫 요청이 새 prefix로 자연히 cache write를 하고, 그날 안의 후속 요청은 read로 누적 hit.
- 즉 "자정 클리어 후 재구성"은 **컨텐츠 교체만** 하면 되고 별도 invalidation 코드가 필요 없다.

### 진짜 문제 — 캡처가 띄엄띄엄일 때 TTL 만료

- 캡처 간격이 TTL(5분/1시간)보다 길면 매 캡처가 **cold write**가 되어 캐싱 이득이 사라진다(매번 1.25×/2× write만 내고 read 누적이 안 됨). 이게 Oracle의 실제 리스크다(일상 디스커버리는 트래픽이 불규칙).

### 대응 (권장 조합)

1. **`ttl:"1h"` 명시** — 5분 기본값에 의존하지 말 것. (커뮤니티에 "2026년 초 기본 TTL이 1h→5m로 회귀"라는 미검증 보고가 있어 더더욱 명시 필요. 공식 문서는 5분 기본/1시간 옵션 병존을 일관 기술.)
2. **keep-warm 프리워밍** — 트래픽 공백이 1시간을 넘길 수 있으면, 자정 직후 + 일정 주기(예: TTL 직전, 1시간마다)로 `max_tokens:0` 프리워밍 요청을 보내 prefix를 warm 유지. cron(자정 LaunchAgent)에 hook.
3. **프리워밍을 무조건 켜지 말 것** — 첫 요청 지연(TTFT)이 사용자에게 보이고, 공백이 TTL보다 길 때만 의미 있다. 캡처가 1시간 안에 꾸준하면 프리워밍은 순수 추가 write 비용일 뿐이니 생략.
4. 한 턴이 20블록을 넘기는 에이전트 루프가 아니므로(Oracle은 단발 인사이트 호출) **20블록 lookback 이슈는 해당 없음.** breakpoint는 4개 한도 내 1~2개로 충분.

---

## Nest 코드 수정점

대상 파일: `/Users/astonlee/projects/nest/backends/api_backend.py`

### (a) `call_anthropic` content 순서 재배치 + system 블록 도입 (90–134행)

현재(101–105행)는 **이미지(가변) → 프롬프트(마지막)** 순이다. 캐싱은 prefix match라 이 순서면 이미지 b64가 매번 prefix를 무효화한다. Oracle의 프리픽스는 "30일 저널 + 지시문"(고정)이므로 **고정 블록을 앞, 가변(오늘 캡처/이미지/질문)을 뒤**로 두고, 고정 블록 끝에 `cache_control`을 단다.

권장 형태(개념):

```python
# 고정 prefix는 system 으로 (캐시 경계 명시)
system = [{
    "type": "text",
    "text": rolling_30day_context,           # + 고정 지시문
    "cache_control": {"type": "ephemeral", "ttl": "1h"},
}]
# messages = 가변(오늘 캡처/이미지/질문)만, 캐시 마커 없음
content = [{"type": "text", "text": prompt}]
for b64 in (image_b64s or []):               # 이미지는 뒤로
    content.append({"type": "image", "source": {...}})
kwargs = {"model": model, "system": system,
          "messages": [{"role": "user", "content": content}], ...}
```

- 현 `call_anthropic` 시그니처엔 `system` 인자도, "고정 prefix"를 구분해 받을 인자도 없다. **Oracle 게이트웨이 호출부에서 30일 컨텍스트를 prompt 본문에 섞지 말고 별도 인자(예: `cache_prefix`/`system`)로 전달**하도록 Nest 인터페이스를 확장해야 한다. (Nest는 "프롬프트 비종속" 설계지만, 캐싱하려면 "어디까지가 고정 prefix인가"를 호출자가 알려줘야 한다 — 이게 핵심 설계 변경.)
- 결정론적 직렬화 필수: 30일 컨텍스트를 JSON으로 만들 때 `sort_keys=True`, 타임스탬프/UUID/`datetime.now()`를 prefix에 절대 섞지 않기. "오늘 날짜"는 가변이므로 messages 뒤쪽으로.

### (b) usage 필드 확장으로 hit 검증 (12–30행 `_result`, 133–134행)

현재 `_result`는 `resp.usage.input_tokens/output_tokens`만 싣는다(25–30, 133–134행). 캐시 hit 관측을 위해 `_result` dict 스키마에 `cache_read_input_tokens`/`cache_creation_input_tokens`를 추가하고 `call_anthropic`에서 `resp.usage.cache_read_input_tokens` 등을 넘긴다. 이 값이 반복 요청에서 계속 0이면 silent invalidator 신호다.

### (c) thinking 분기 모델 호환 (108–113행) — 캐싱과 함께 처리할 선결 이슈

Opus 4.8/4.7을 쓸 거면 `thinking={"type":"enabled","budget_tokens":...}`가 400을 낸다. `adaptive` + `output_config={"effort":...}`로 바꿔야 한다(`EFFORT_BUDGET` 매핑은 effort 문자열로 대체). 캐싱 무효화 계층상 thinking on/off·effort 변경은 **messages만 무효화하고 system(=30일 prefix) 캐시는 살아있다** → 캐싱과 충돌 없음.

### (d) keep-warm / 프리워밍 (자정 대응)

띄엄띄엄 캡처용. `max_tokens:0` 프리워밍 요청을 자정 직후 1회(또는 TTL 직전 주기적으로) 보내는 헬퍼를 Oracle 측 cron(이미 자정 LaunchAgent 존재)에 추가. `max_tokens:0`은 stream/thinking enabled/tool_choice tool|any 등과 함께 쓰면 400이므로 단순 prefill 요청으로만.

### (e) OpenAI / openai_compat — 변경 거의 불필요

- `call_openai`(137–169행)·`call_openai_compat`(41–87행)는 자동 캐싱이라 코드 변경 불필요. 단 `_content_parts_openai`(33–38행)가 이미 **text 먼저(34행) → image 뒤(35–37행)**라 "같은 프리픽스 + 다른 이미지" 패턴에 유리하다(Anthropic 쪽과 순서가 반대였던 점이 여기선 이득). 30일 컨텍스트를 쓰려면 이쪽도 **고정 컨텍스트를 messages 앞, 오늘 질문을 뒤**로 배치하면 자동 캐싱이 붙는다.
- codex CLI(`call_codex`, cli_backend.py 119–136행)는 OpenAI 백엔드 경유 시 자동 혜택을 받지만 CLI엔 제어/관측 수단이 없다.

---

## 최종 권고 + 구현 단계

### 경로

즉답 인사이트(Layer 1)의 주 모델을 **Claude API(anthropic provider) + `cache_control`**로. 30일 프리픽스를 `system` 블록에 `ttl:"1h"`로 캐싱. Gemini는 캐싱 경로로 승격하지 않고(실익 낮음, auth 전환 부담) 보조 모델로 유지. OpenAI는 구조만 맞추면 자동 캐싱이 따라옴.

### Nest 구현 단계 (순서대로)

1. **인터페이스 확장**: 게이트웨이 호출부에서 "30일 고정 prefix"를 prompt 본문과 분리해 별도 인자로 전달(예: `system`/`cache_prefix`). 이게 모든 캐싱의 전제.
2. **`call_anthropic` 수정** (`api_backend.py` 90–134행): 고정 prefix → `system=[{...,"cache_control":{"type":"ephemeral","ttl":"1h"}}]`, 가변(이미지·오늘 캡처·질문)은 messages 뒤로. 30일 컨텍스트는 결정론적 직렬화(`sort_keys=True`, 타임스탬프/UUID 배제).
3. **thinking 분기 모델 호환** (108–113행): Opus 4.8/4.7 사용 시 `adaptive` + `output_config.effort`로 전환(`budget_tokens`는 400). 이건 캐싱과 독립적으로도 필요.
4. **usage 관측** (12–30, 133–134행): `_result`에 `cache_read_input_tokens`/`cache_creation_input_tokens` 추가 → hit률 모니터링. 반복 요청에서 read가 0이면 invalidator 추적.
5. **keep-warm**: 자정 LaunchAgent에 `max_tokens:0` 프리워밍 hook 추가(공백 > TTL인 경우만 활성). 자정 윈도우 교체는 "강제 무효화" 없이 컨텐츠 교체만.
6. **OpenAI 경로 정합화**: 30일 컨텍스트 사용 시 `call_openai`/`call_openai_compat`도 고정 컨텍스트 앞·질문 뒤로 배치(코드 변경 최소, 자동 캐싱이 붙음).
7. **검증**: 같은 날 2회+ 캡처로 `cache_read_input_tokens > 0` 확인, 자정 직후 첫 요청에서 `cache_creation_input_tokens`가 한 번만 뜨는지 확인.

### 핵심 주의 3가지

1. prefix에 `datetime.now()`/UUID/비결정론적 JSON 절대 금지(섞이면 캐시 0%).
2. TTL은 `1h` 명시(기본값 의존 금지).
3. 모델 전환 시 최소 prefix(Opus 4.7/4.6=4,096) 및 thinking 파라미터 차이 재확인.

---

## 관련 파일

- `/Users/astonlee/projects/nest/backends/api_backend.py`
  - `call_anthropic` 90–134행
  - `_result` 12–30행
  - `_content_parts_openai` 33–38행
  - `call_openai` 137–169행
  - `call_openai_compat` 41–87행
- `/Users/astonlee/projects/nest/backends/cli_backend.py`
  - `call_gemini` 150–176행 (CLI 캐싱 불가 지점)
  - `call_codex` 119–136행
