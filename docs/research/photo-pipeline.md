# 사진 3단계 처리 파이프라인 — 딥리서치 정리

> 주제: VLM(비전 언어 모델) 사진 다단계 처리 파이프라인 — 사진 한 장을 (1) 상세 분석(객체·장면·OCR·속성·관계) → (2) 맥락(직전 대화/기억) 기반 코멘트 → (3) 디스커버리/능동적 제안, 의 3단계로 분리 처리하는 패턴 설계를 위한 참조 조사.
>
> 조사 통계: 5개 앵글 · 23개 출처 fetch · 111개 claim 추출 · 25개 검증 → **16 confirmed / 9 killed** · 합성 후 7개 발견 · agent 호출 105회.

---

## TL;DR

조사 결과는 Oracle의 **"분석→코멘트→제안" 3단계 분리 설계를 강하게 뒷받침**한다. 핵심 결론:

1. **단일 패스 = 인식 오류 전파.** VLM에서 시각 인식(perception)과 추론(reasoning)을 한 번에 뒤섞는 단일 패스는 작은 인식 오류가 답 전체로 전파되는 실패 모드를 낳는다. 인식을 먼저 견고히 다진 뒤 추론하는 단계 분리가 여러 모델·벤치마크에서 측정 가능한 정확도 향상을 가져온다.
   - CCoT: GPT-4V SEED-I **+4.9**, Winoground-Group **+9.8**
   - SPARC: V* VQA **+6.7pp**
   - Img2Prompt: VQAv2에서 Flamingo-80B 대비 **+5.6점**

2. **직접 베낄 템플릿 = CCoT 2단계 방식.** 1단계에서 LMM이 이미지로부터 `objects`/`attributes`/`relationships` 3필드 JSON 씬그래프를 생성하고, 2단계에서 그 JSON을 이미지·태스크와 함께 **같은 모델**에 다시 넣어 최종 응답을 만든다. **fine-tuning 없이 순수 프롬프팅만으로 동작**해 Nest 게이트웨이 경유·미세조정 불가라는 Oracle 제약에 정확히 부합한다.

3. **"말로만 길게" 추론은 역효과.** 텍스트-only CoT는 인식 집약 태스크(카운팅·공간·깊이)에서 오히려 성능을 떨어뜨린다. 2·3단계 추론은 1단계가 추출한 **시각 근거에 충실히 묶여 있어야(visual grounding)** 한다.

4. **구조화 출력 강제 방법은 게이트웨이에 달림.** 1단계 구조화 출력은 NVIDIA NIM의 JSON 스키마/정규식/문법 제약이나 Outlines 같은 constrained decoding으로 강제 가능하나 — 이는 logit 접근 또는 서버측 JSON 모드를 요구하므로, Nest 게이트웨이가 무엇을 노출하느냐에 따라 적용 방식(서버측 스키마 vs Pydantic 사후검증)이 갈린다.

**가장 중요한 한계:** CCoT/SPARC/Img2Prompt는 모두 닫힌형 VQA·구성적 추론 벤치마크를 대상으로 검증되었고, Oracle이 원하는 **3단계(능동적 제안/디스커버리)는 어느 논문도 직접 다루지 않아** 1·2단계는 강하게 근거되지만 3단계는 외삽이다.

---

## 핵심 발견

### 1. 단일 패스는 인식 오류를 답 전체로 전파시킨다 (단계 분리의 핵심 동기)

**Claim.** 인식과 추론을 단일 패스에서 뒤섞으면 작은 인식 오류가 답 전체로 전파되는(cascade) 실패 모드가 발생하며, 이것이 두 단계를 분리하는 핵심 동기다. 인식을 먼저 견고히 다지면 과도한 추론의 필요가 줄어든다 (분리 학습 시 추론 정확도 **+1.5%**, 추론 trace 길이 **-20.8%**).

**근거.**
- **SPARC**(2602.06566) 초록 verbatim: *"unstructured chains-of-thought about images entangle perception and reasoning, leading to long, disorganized contexts where small perceptual mistakes may cascade into completely wrong answers."*
- **From Seeing to Thinking**(2605.20177): 본 방식 학습 모델이 *"+1.5% higher reasoning accuracy with 20.8% shorter reasoning traces, suggesting that superior perception reduces the need for excessive reasoning."*
- 2025–26 다수 독립 논문(Seeing but Not Believing 2510.17771, Caption This Reason That 2505.21538, Chain-of-Visual-Thought 2511.19418)이 동일 명제(perception이 dominant bottleneck)로 수렴.
- **캐비엇:** Perception-Time Scaling 등은 인식+추론을 '보완적'으로 보고 올바른 인식은 필요조건이나 충분조건은 아니라고 단서. 수치는 특정 백본(Qwen2.5/3-VL) 한정.

**Confidence:** high · **Vote:** 3-0 (양 클레임 모두 만장일치)

**출처:**
- https://arxiv.org/abs/2605.20177
- https://arxiv.org/pdf/2602.06566

> **Oracle 적용:** `agent/vision.py`가 분석 JSON을 별도 1단계로 먼저 확정한 뒤 코멘트/제안으로 넘기는 현 구조가 정확히 이 cascade 방지 동기에 부합 — 분석을 코멘트 생성과 한 프롬프트에 섞지 말 것.

---

### 2. 직접 베낄 핵심 템플릿 = CCoT 2단계 파이프라인

**Claim.** 직접 베낄 수 있는 핵심 템플릿은 CCoT의 2단계 파이프라인이다: 1단계에서 LMM이 이미지+태스크로부터 `objects`/`attributes`/`relationships` 3필드 JSON 씬그래프를 생성하고, 2단계에서 이미지+태스크+생성된 씬그래프를 **같은 LMM에 joint context로 다시 넣어** 최종 응답을 만든다. 이것이 Oracle의 분석→구조화 핸드오프→추론 구조에 직접 매핑된다.

**근거.**
- CVPR 2024 peer-reviewed, 공식 코드 `github.com/chancharikmitra/CCoT`.
- 초록 verbatim: *"we first generate an SG using the LMM, and then use that SG in the prompt to produce a response."*
- 2단계 verbatim: *"The LMM is thus prompted with the original task prompt, image, and corresponding generated scene graph so that all three can be jointly used as context to respond."*
- 1단계 프롬프트는 *"objects, their attributes, and the relationships between them"*을 JSON으로 생성하도록 지시. **동일 LMM 사용**(별도 모델 불필요).
- **캐비엇:** CCoT는 2단계(인지→답변)이지 3단계가 아니며 구성적 VQA 정확도가 타깃이라 Oracle의 1·2단계만 강하게 근거하고 3단계(능동 제안)는 미커버. 'directly transferable'의 'directly'는 약한 과장 — 대화형 코멘트/제안은 별도 레이어.

**Confidence:** high · **Vote:** 3-0 (claim 1, 11 모두 만장일치)

**출처:**
- https://arxiv.org/abs/2311.17076
- https://arxiv.org/html/2311.17076v3

> **Oracle 적용:** Oracle 3단계는 같은 VLM을 재호출하는 CCoT 골격을 그대로 차용하되, 코멘트(2)·제안(3)은 CCoT가 다루지 않는 별도 레이어로 명시 — 1단계 JSON을 2·3단계 프롬프트에 joint context로 넣는 핸드오프만 CCoT에서 복사.

---

### 3. 인식/추론 분리는 4개 LMM에서 측정 가능한 정확도 향상 (fine-tuning·GT 주석 불필요)

**Claim.** 인식(씬그래프 생성)을 추론에서 분리하면 4개 서로 다른 LMM(InstructBLIP-13B, LLaVA-1.5-13B, Sphinx, GPT-4V)에서 구성적·일반 멀티모달 벤치마크 양쪽 모두 측정 가능한 정확도 향상이 나온다.

| 모델 | 벤치마크 | from → to | 델타 |
|---|---|---|---|
| GPT-4V | SEED-I | 69.1 → 74.0 | +4.9 |
| GPT-4V | MMBench | 75.5 → 76.3 | +0.8 |
| GPT-4V | LLaVA-Wild | 88.2 → 91.2 | +3.0 |
| GPT-4V | Winoground-Group | 33.5 → 43.3 | +9.8 |
| LLaVA-1.5-13B | Winoground-Group | 17.3 → 22.3 | +5.0 |

**fine-tuning이나 ground-truth 씬그래프 주석 없이 달성.**

**근거.**
- Table 1의 from→to 수치 5개 전부 정확히 일치(arxiv HTML v3 + CVPR openaccess PDF 양쪽 대조). 4개 LMM 확인.
- *"without the need for fine-tuning or annotated ground-truth SGs"* verbatim.
- **캐비엇:** LLaVA-Wild 델타가 원문에 '(+2.0)'으로 표기됐으나 실제 88.2→91.2는 +3.0 — 6개 델타 중 1개의 전사 오류이며 load-bearing from/to 값은 정확. 작은 모델에서는 효과가 미미(LLaVA-1.5-7B-CCoT ~+0.1%)할 수 있어 **이득은 모델 규모 의존적.**

**Confidence:** high · **Vote:** 3-0

**출처:**
- https://arxiv.org/abs/2311.17076

> **Oracle 적용:** Nest 게이트웨이가 호출하는 주 모델이 충분히 큰 모델일 때만 분리 이득이 유의미 — 설정에서 작은 로컬 모델을 고를 경우 3단계 분리의 정확도 이득은 ~0에 수렴할 수 있으니 모델 선택과 묶어 평가.

---

### 4. 1단계 출력 = 태스크 조건화된 구조화 JSON (단, Oracle엔 scene·OCR 필드 추가 필요)

**Claim.** 1단계 출력은 정확히 3개 필드(`objects`, `attributes`, `relationships`)를 가진 구조화 JSON이어야 하며, 프롬프트는 태스크를 명시적으로 조건화해 씬그래프가 관련성을 유지하게 한다. 이것이 Oracle 1단계 출력의 복사 가능한 출발 스키마다. 단일 VLM 패스로 caption·question·quality 같은 여러 typed 필드를 한 JSON 객체에 동시 추출 가능하다.

**근거.**
- CCoT Fig 2 실제 출력이 정확히 3개 top-level 키 `{objects, attributes, relationships}`.
- 태스크 조건화 verbatim: *"We include both the image I and task prompt Pin... to condition the generated scene graph to be relevant to the given task prompt"* (씬그래프는 long-tailed라 이미지만으로는 무관 정보 포함).
- HF cookbook: 단일 호출 `outlines.generate.json(model, ImageData)`로 `class ImageData(BaseModel): quality: str; description: str; question: str` 3필드 동시 생성 (claim 14, 3-0).
- **중요 적합성 한계 (claim 3은 2-1 split):** CCoT 씬그래프는 의도적으로 '최소화·태스크 조건화'되어 특정 질문에 불필요한 것을 배제 — Oracle의 **'최대한 자세히(maximally detailed)' 목표와 방향이 반대.** 또한 CCoT 3필드에는 `scene`/setting 필드도 OCR/텍스트 필드도 없는데 Oracle은 둘 다 명시적으로 요구. 따라서 3필드는 출발점이되 Oracle용으로는 **불완전 — `scene`·`ocr_text` 필드 추가 필요.**

**Confidence:** high · **Vote:** claim 3: 2-1 (split, 적합성 한계), claim 14: 3-0

**출처:**
- https://arxiv.org/abs/2311.17076
- https://huggingface.co/learn/cookbook/en/structured_generation_vision_language_models

> **Oracle 적용:** `agent/vision.py`의 분석 JSON `{objects, attributes, relationships, scene, ocr_text}`은 CCoT 3필드를 정확히 슈퍼셋으로 확장한 형태로 이미 옳은 방향 — 단 CCoT의 '태스크 조건화 최소화'와 Oracle의 '최대한 자세히'가 충돌하므로, 캡처 시점엔 태스크 질문이 없다는 점을 감안해 일반-상세 추출로 갈지 트레이드오프 결정 필요.

---

### 5. 텍스트-only CoT는 인식 집약 태스크에서 역효과 — 추론은 시각 근거에 묶여야

**Claim.** 텍스트-only CoT는 vision-centric/인식 집약 태스크(카운팅, 공간 대응, 상대 깊이)에서 성능 향상에 실패하고 오히려 떨어뜨린다 — Qwen3-VL은 언어 CoT 사용 시 공간 이해에서 instruct 베이스라인 대비 **5% 이상 악화.** 따라서 추론 단계를 '말로만' 길게 늘리는 것은 역효과이며, 추론은 시각 근거에 충실히(visual grounding) 묶여야 하고 **유창한 서술 ≠ 충실한 추론**이다.

**근거.**
- **Chain-of-Visual-Thought**(2511.19418, UC Berkeley) verbatim: *"text-only CoT not only fails to improve performance on vision-centric reasoning tasks, but often degrades it ... Qwen3-VL performing over 5% worse than Qwen3-VL-Instruct with language CoT on spatial understanding."*
- 독립 코로보레이션: NYU VSI-Bench는 *"CoT, self-consistency, tree-of-thoughts가 공간 추론에서 1-4% 성능 저하"*.
- **MM-CoT**(2512.08228) verbatim: *"sharp discrepancy between generative fluency and true reasoning fidelity"* — 모든 단계가 *"anchored in observable evidence"*여야 함(Visual Grounding Constraint).
- **캐비엇:** 정확한 '5%'는 대안(CoVT) 제안 논문의 동기 수치로 표 원본 미재현; MM-CoT는 막 나온 단일 벤치마크라 'one recent benchmark finds'로 인용 권장. CoT가 도움되는 경우는 지식기반 VQA로 인식 집약 태스크가 아님 — 본 클레임 범위와 무관.

**Confidence:** high · **Vote:** 3-0 (양 클레임 모두 만장일치)

**출처:**
- https://arxiv.org/html/2511.19418v1
- https://arxiv.org/html/2512.08228v1

> **Oracle 적용:** 2단계 코멘트·3단계 제안 프롬프트가 "단계적으로 생각해보라"식 장황한 텍스트 CoT를 유도하면 오히려 품질 저하 — 코멘트/제안은 반드시 1단계 JSON의 `objects/ocr_text/scene` 항목을 명시적으로 인용·근거하도록 프롬프트를 grounding에 묶을 것.

---

### 6. 인식을 텍스트로 변환해 frozen LLM에 넘기면 end-to-end 학습 없이 zero-shot VQA 가능 (describe-then-reason 실증)

**Claim.** 인식을 이미지→텍스트로 변환해(이미지 설명 + 자기생성 QA 쌍의 **두 종류 중간 텍스트 표현**) frozen·off-the-shelf LLM에 raw visual feature 대신 프롬프트로 넘기면, end-to-end 멀티모달 학습 없이 zero-shot VQA가 가능하며 end-to-end 학습 방법과 동등하거나 더 낫다. 이는 인식(이미지→텍스트)과 추론(LLM)을 분리하는 아키텍처의 실증이다.

**근거.**
- **Img2Prompt/Img2LLM**, CVPR 2023(openaccess), 공식 코드 Salesforce LAVIS.
- 두 종류 중간 표현 verbatim: *"image captions and synthetic QA pairs—rather than raw visual features."*
- 비교표에 모든 Img2Prompt 변형 *"End-to-End Training? = x"* vs Flamingo *"✓"*.
- 정량: VQAv2에서 **Flamingo-80B 대비 +5.6점**(Img2LLM OPT-175B 61.9 vs 56.3), A-OKVQA에서 few-shot 대비 **최대 +20%**. 선행 PICa(AAAI 2022)도 동일 분리 명제 지지.
- **캐비엇:** VQA(주어진 질문 답변) 한정으로 Oracle의 개방형 describe→comment→제안보다 좁음 — 아키텍처 타당성은 일반화되나 '동등/우월' 벤치마크 수치는 VQA 특정. 'off-the-shelf'는 LLM에만 해당; 인식 프론트엔드(BLIP)는 학습된 모델. **OK-VQA에서는 Flamingo-80B에 패배**(전면적 우월 아님). 2022년 논문이라 SOTA로 인용 금지, describe-then-reason 패턴의 벤치마크 근거로만 사용.

**Confidence:** high · **Vote:** claim 6,7: 3-0; claim 8: 2-1 (수치 verbatim 확인, '5.6%'는 5.6 포인트)

**출처:**
- https://arxiv.org/abs/2212.10846

> **Oracle 적용:** 1단계가 이미지를 텍스트(JSON)로 변환해두면 2·3단계는 시각 입력 없이 텍스트만으로 동작 가능 — Nest 게이트웨이에서 base64 이미지 재전송 비용을 2·3단계에서 절약할 여지(단 grounding 손실 트레이드오프, 발견 5 참조).

---

### 7. 1단계 구조화 출력은 decode 시점에 강제 가능 (NIM/Outlines) — 단 게이트웨이가 logit/JSON 모드 노출해야

**Claim.** 1단계 구조화 출력은 프롬프팅에 기대지 않고 decode 시점에 강제할 수 있다. NVIDIA NIM은 VLM 출력을 JSON 스키마/정규식/CFG 문법/열거형 선택지로 제약하며, Outlines 라이브러리는 Pydantic BaseModel을 정규식→FSM으로 변환해 매 토큰에서 유효하지 않은 토큰의 logit을 -무한대로 마스킹(constrained decoding)한다.

**근거.**
- NVIDIA NIM 공식 문서 verbatim: *"NIM for VLMs supports getting structured outputs by specifying a JSON schema, regular expression, context free grammar, or constraining the output to some particular choices"* (`response_format`/`guided_regex`/`guided_grammar`/`guided_choice`). v1.3.0~v1.7.0 안정 유지 확인.
- Outlines 메커니즘: JSON schema→regex→FSM, 각 토큰 단계서 무효 토큰 logit -inf 마스킹.
- **중요 아키텍처 캐비엇:** decode-time logit 마스킹은 logit/토큰 확률 접근을 요구해 로컬 VLM엔 동작하나 **logit을 노출하지 않는 순수 원격 게이트웨이엔 불가** — Oracle은 Nest 게이트웨이 경유이므로 (a) 게이트웨이가 서버측 JSON/문법 모드를 노출하면 그것을 쓰고 (b) 아니면 **Pydantic 사후검증으로 폴백**해야 함. NIM `nvext` 필드는 'OpenAI 엔드포인트만 노출'. 부차 한계: 복잡한 다층 중첩 Pydantic은 regex 변환이 불안정해질 수 있음.

**Confidence:** high · **Vote:** 3-0 (claim 13, 15 모두 만장일치)

**출처:**
- https://docs.nvidia.com/nim/vision-language-models/1.0.0/structured-generation.html
- https://huggingface.co/learn/cookbook/en/structured_generation_vision_language_models

> **Oracle 적용:** Oracle은 Nest 게이트웨이 경유라 logit 접근이 없을 가능성이 크므로 — `agent/vision.py` 1단계 JSON은 게이트웨이의 서버측 JSON 모드 지원 여부를 먼저 확인하고, 미지원 시 프롬프트 지시 + Pydantic 사후검증/재시도 폴백으로 강제(미해결 질문 1 참조).

---

## 주의·한계 (caveats)

- **시간 민감성:** 핵심 1차 출처 다수가 매우 최신(SPARC 2602.06566 = 2026-02, From Seeing to Thinking 2605.20177 = 2026-05로 컨텍스트 시점 ~3주 전, Chain-of-Visual-Thought·MM-CoT = 2025-11~12)이라 아직 독립 재현이 부족한 것이 있음. 특히 MM-CoT와 '5% 악화' 수치는 각각 신규 벤치마크/대안 제안 논문의 자체 framing이므로 **'one recent benchmark finds'로 인용 권장**, 정착된 합의로 단정 금지. 반면 **CCoT(CVPR 2024)와 Img2Prompt(CVPR 2023)는 peer-reviewed·널리 인용·공식 코드 보유로 가장 견고.**
- **출처 품질:** 전 16 클레임이 primary(arXiv 논문 또는 벤더 공식 문서)이며 블로그/포럼 출처 없음 — 단 일부 메커니즘 세부(Outlines logit 마스킹)는 secondary 기술 블로그로 보강됨.
- **일반화 한계:** 벤치마크 이득 수치는 모두 특정 백본(Qwen2.5/3-VL, GPT-4V, LLaVA-1.5, OPT) 한정이라 보편 법칙이 아니며 **모델 규모 의존적**(작은 모델에선 CCoT 이득 ~+0.1%로 미미).
- **가장 중요한 미스핏:** CCoT/SPARC/Img2Prompt는 전부 닫힌형 VQA·구성적 추론 벤치마크를 타깃으로 검증됐고, Oracle이 진짜 원하는 **3단계(능동적 제안/디스커버리)와 대화형 코멘트는 어떤 1차 출처도 직접 측정하지 않음** — Cognitive CoT(2507.20409)는 CCoT식 시각 파싱이 *'의도·적절성 추론에 필요한 해석적 scaffolding에 미달'*한다고 명시. 따라서 분석(1단계)·구조화 핸드오프(1→2)는 강하게 근거되나, **제안/디스커버리(3단계)의 품질 향상은 본 조사가 직접 입증하지 못한 외삽**이다.
- **1단계 목표 충돌:** Oracle 1단계 목표('최대한 자세히')는 CCoT 씬그래프의 '태스크 조건화 최소화' 철학과 방향이 반대이고 `scene`/OCR 필드가 빠져 있어 **스키마를 그대로 복사하면 안 되고 확장 필요.**
- **반증된 클레임의 의미:** 반증된 클레임들(특히 JSON 형식 자체가 인과적 원인이라는 ablation 주장 2건은 0-3/1-2로 기각, 인식이 '주된' 병목이라는 강한 주장도 1-2로 기각)은 **'구조화가 도움될 수 있다'까지만 지지**하며 **'구조화 JSON이 free-text보다 인과적으로 우월'은 본 조사에서 확립되지 않았음.**

### 참고: 반증된(killed) 클레임 목록

조사 과정에서 검증에 실패해 기각된 주요 클레임 (Oracle 설계 시 **근거로 사용 금지**):

| 기각된 클레임 (요약) | Vote | 출처 |
|---|---|---|
| VLM 성능의 '주된' 병목은 추론이 아니라 인식이며, 분리 학습이 인식·추론 모두 일관 향상 | 1-2 | https://arxiv.org/abs/2605.20177 |
| VLM post-training을 인식·시각추론·텍스트추론 3단계로 분해하는 것이 본 연구 방법론 | 0-3 | https://arxiv.org/abs/2605.20177 |
| JSON 구조화 자체가 인과 원인 — JSON 포맷 제거 시 가중정확도 -2.0, 평문 caption 대체 시 -1.4 | 1-2 | https://arxiv.org/abs/2311.17076 |
| 연속 시각 정보를 이산 텍스트로 투영하면 저수준 단서(경계·레이아웃·깊이·기하) 손실이 핵심 원인 | 1-2 | https://arxiv.org/html/2511.19418v1 |
| 구조화 CoT가 직접답변 대비 대폭 우월 (Qwen2.5-VL-72B +12.2pt, GPT-5 +12.8pt) | 0-3 | https://arxiv.org/html/2512.08228v1 |
| 중간 씬그래프가 JSON으로 명시 조건화 + ablation으로 평문 caption 대체 시 -2.0% | 0-3 | https://arxiv.org/html/2311.17076v3 |
| 인식/추론 분리가 다모델·다태스크 이득 (Winoground +9.8, WHOOPS! +13.9, MMBench +3.7 등) | 0-3 | https://arxiv.org/html/2311.17076v3 |
| 구조화 중간표현+전용 추론이 near-human VQA (수동 큐레이션 씬그래프 90.63% vs 인간 89.3%) | 0-3 | https://arxiv.org/pdf/2007.01072 |
| 파이프라인이 인식(씬그래프)과 추론(RL 에이전트 그래프 탐색)을 명시 분리 = 정석 describe-then-reason | 0-3 | https://arxiv.org/pdf/2007.01072 |

---

## 미해결 질문 (openQuestions)

1. **Nest 게이트웨이가 실제로 무엇을 노출하는가** — 서버측 JSON 스키마/문법 모드(NIM `nvext` 또는 OpenAI호환 `response_format`)를 지원하는가, 아니면 logit 접근이 없어 Pydantic 사후검증 폴백만 가능한가? 이것이 1단계 구조화 출력 강제 방식을 결정하므로 코드/게이트웨이 문서 확인 필요(`backend/nest_client.py`).
2. **3단계(능동적 제안/디스커버리)를 위한 검증된 프롬프트·기법은 본 조사에서 직접 찾지 못함** — 사진으로부터 흥미로운 관점·연결·실용 조언을 끌어내는 패턴은 VQA 논문 범위 밖이므로, 개방형 생성/추천 도메인의 별도 조사(이미지 기반 추천, proactive assistant 프롬프팅)가 필요한가?
3. **Oracle 1단계 스키마의 최적 필드 집합은 무엇인가** — CCoT의 `objects`/`attributes`/`relationships`에 `scene`/setting, `ocr_text`, 그리고 2·3단계가 필요로 할 사용자 맥락 hook 필드를 어떻게 추가할 것이며, '최대한 자세히'와 '태스크 조건화 관련성 유지'의 트레이드오프를 Oracle 캡처 시나리오에서 어떻게 조정할 것인가?
4. **단계 분리에 따른 지연시간/비용 증가**(VLM 호출 2~3회 + 토큰 증가)가 Oracle의 '즉답 인사이트' UX 목표와 충돌하는가 — SPARC는 토큰 예산을 오히려 줄였다고 보고하나 CCoT/Img2Prompt는 추가 패스를 요구하므로, 실제 Nest 경유 base64 이미지 전송 비용 하에서 3단계가 실용적인지 측정 필요.

---

## 참조 출처 (sources)

| # | URL | Title / 식별 | Quality | 앵글 | claims |
|---|---|---|---|---|---|
| 1 | https://arxiv.org/abs/2605.20177 | From Seeing to Thinking | primary | academic/benchmarks | 5 |
| 2 | https://arxiv.org/abs/2311.17076 | CCoT (Compositional CoT, CVPR 2024) | primary | academic/benchmarks | 5 |
| 3 | https://arxiv.org/pdf/2602.06566 | SPARC | primary | academic/benchmarks | 5 |
| 4 | https://arxiv.org/abs/2212.10846 | Img2Prompt / Img2LLM (CVPR 2023) | primary | academic/benchmarks | 4 |
| 5 | https://arxiv.org/html/2511.19418v1 | Chain-of-Visual-Thought (UC Berkeley) | primary | academic/benchmarks | 5 |
| 6 | https://arxiv.org/html/2512.08228v1 | MM-CoT | primary | academic/benchmarks | 5 |
| 7 | https://arxiv.org/html/2311.17076v3 | CCoT v3 (HTML) | primary | structured intermediate output | 5 |
| 8 | https://huggingface.co/learn/cookbook/en/structured_generation_vision_language_models | HF Cookbook — Structured Generation VLM | primary | structured intermediate output | 5 |
| 9 | https://www.eventual.ai/blog/multimodal-structured-outputs-evaluating-vlm-image-understanding-at-scale | Eventual.ai — Multimodal Structured Outputs | blog | structured intermediate output | 4 |
| 10 | https://developers.redhat.com/articles/2025/06/03/structured-outputs-vllm-guiding-ai-responses | Red Hat — Structured Outputs in vLLM | blog | structured intermediate output | 5 |
| 11 | https://arxiv.org/pdf/2007.01072 | (씬그래프+RL 에이전트 VQA) | primary | structured intermediate output | 5 |
| 12 | https://docs.nvidia.com/nim/vision-language-models/1.0.0/structured-generation.html | NVIDIA NIM for VLMs — Structured Generation | primary | structured intermediate output | 5 |
| 13 | https://arxiv.org/html/2505.14668v1 | (practitioner — proactive/discovery) | primary | practitioner — proactive suggestion | 5 |
| 14 | https://arxiv.org/html/2512.06721v1 | (practitioner — proactive/discovery) | primary | practitioner — proactive suggestion | 5 |
| 15 | https://developer.nvidia.com/blog/vision-language-model-prompt-engineering-guide-for-image-and-video-understanding/ | NVIDIA — VLM Prompt Engineering Guide | primary | practitioner — proactive suggestion | 5 |
| 16 | https://github.com/microsoft/SoM | Microsoft Set-of-Mark (SoM) | primary | reference architectures | 5 |
| 17 | https://github.com/allenai/visprog | AllenAI VisProg | primary | reference architectures | 5 |
| 18 | https://arxiv.org/pdf/2411.16034 | (reference architecture) | primary | reference architectures | 5 |
| 19 | https://arxiv.org/html/2408.16224v1 | (reference architecture) | primary | reference architectures | 5 |
| 20 | https://arxiv.org/abs/2604.02460 | (cost/latency/hallucination 다단계) | primary | contrarian/skeptical | 4 |
| 21 | https://arxiv.org/pdf/2509.25848 | (cost/latency/hallucination 다단계) | primary | contrarian/skeptical | 5 |
| 22 | https://learnagentic.substack.com/p/what-is-error-cascading-in-multi | LearnAgentic — Error Cascading in Multi-agent | blog | contrarian/skeptical | 4 |
| 23 | https://towardsdatascience.com/the-multi-agent-trap/ | TDS — The Multi-Agent Trap | blog | contrarian/skeptical | 5 |
