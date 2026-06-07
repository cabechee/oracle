# 계층적 메모리(단기/장기) — 딥리서치 정리

> 주제: **LLM 에이전트의 계층적 메모리(단기/장기 기억) 시스템**
> 목적: 일/주/월 다이제스트(요약)를 '기억 계층'으로 활용해 단기·장기 기억을 분류하고 약 6개월 유지하는 메모리 아키텍처를 설계하기 위한 참조 조사.
> 맥락: Oracle = 개인 일상 캡처(사진/메모/음성) → 즉답 인사이트(LLM) + 일/주/월 다이제스트(cron 배치) + 자연어 질의(임베딩 검색). 스택 = FastAPI + MongoDB.
> 조사 규모: 5개 앵글 · 24개 출처 fetch · 119개 claim 추출 · 25개 검증(21 confirmed / 4 killed) · 7개 발견으로 합성.

---

## TL;DR

계층적 메모리는 학계·오픈소스 모두에서 **(1) 분류 → (2) 승급(consolidation) → (3) 망각(forgetting/decay) → (4) 검색**의 라이프사이클으로 수렴한다.

- **분류**: 단기/장기 구분은 "시간(현재 세션 vs 영속 기록)" 또는 "상호작용 범위(in-trial vs cross-trial)" 기준이 표준이다. 다만 최신 대형 서베이(arXiv:2512.13564)는 순수 시간 분할을 **버리고** factual/experiential/working의 **기능적 분류**를 권한다. 즉 Oracle은 "원본 캡처=일화(episodic)/단기, 다이제스트=의미(semantic)/장기"라는 **기능 축**으로 분류하는 것이 정석이다.
- **승급**: 핵심 패턴은 두 갈래. **MemoryBank·Recursive Summarization**은 "하나의 누적 요약을 롤링 재귀 갱신", **Generative Agents**는 "원본 스트림 위에 reflection을 주기적으로 합성하는 다층 트리"다. Oracle의 일→주→월 다이제스트는 후자(계층적 요약-of-요약)에 정확히 대응한다.
- **망각·압축 손실**: 반복 압축은 저빈도·희귀 사실을 잃는 "sanitized/generic" 드리프트를 일으킨다. **원본 corpus 보존이 필수 방어책**이다(Oracle은 이미 corpus 불변이라 충족).
- **검색**: 단기(recency)·관련도(임베딩 유사도)·중요도를 가중 결합하는 **Generative Agents식 3-요소 스코어**가 표준 해법이다. Oracle의 현재 `query.py`는 임베딩 top-k + 최근순 fallback뿐이라, recency·중요도(이미 존재하는 reaction 신호) 결합과 다이제스트 계층의 명시적 장기 컨텍스트 주입이 **가장 큰 개선 여지**다.

---

## 핵심 발견

총 **7개 발견**. 각 항목에 claim 본문 + 근거(evidence) 요약 + confidence + 출처 + vote + **Oracle 적용** 한 줄을 붙였다.

### 1. 단기/장기 분류 기준 — 시간 축·상호작용 범위 축, 그리고 인지 4계층

**Claim.** 단기/장기 분류 기준은 '시간 범위'(현재 세션 vs 영속 cross-session 기록)와 '상호작용 범위'(in-trial 관찰=단기 vs cross-trial 경험=장기)의 **두 축**이 표준이다. 더 나아가 최신 인지구조 분류는 **working/episodic/semantic/procedural 4계층**으로 세분하며, 핵심 난제는 **'episodic 기록이 언제 semantic으로 승급되는가'라는 transition policy**다. Oracle 매핑: 원본 캡처(사진/메모/음성)=episodic·단기, 일/주/월 다이제스트=semantic·장기, 자정 배치가 transition policy 역할.

**근거.** 세 편의 1차 서베이가 일치.
- arXiv:2404.13501(ACM TOIS 게재): 'inside-trial observations serve as short-term memory, the trial experiences can be considered as long-term memory' — **범위 기준**.
- arXiv:2505.00675(Du et al. 2025): 'Short-term memory refers to the recent observations like the current dialogue session context, while long-term memory refers to the persistent records of cross-session ... and personal persistent knowledge' — **시간 범위 기준**.
- arXiv:2603.07670v1(2026): working(context window)/episodic(concrete experiences·tool calls·turns)/semantic(de-contextualized knowledge)/procedural(reusable skills) **4계층** + 'The hard question is the transition policy: when does an episodic record graduate to semantic status'. CoALA(arXiv:2309.02427) 계보이며 Letta/Mem0/LangChain이 채택.

**Confidence.** high
**Vote.** claim[0] 2-1, claim[4] 3-0, claim[8] 3-0 — merged
**출처.**
- https://arxiv.org/abs/2404.13501
- https://arxiv.org/abs/2505.00675
- https://arxiv.org/html/2603.07670v1

**Oracle 적용.** 분류축을 시간(단기/장기)이 아니라 기능(원본 캡처=episodic / 다이제스트=semantic)으로 잡고, 자정 cron 배치를 episodic→semantic 승급(transition policy)의 구현체로 설계한다.

---

### 2. 승급(consolidation)·망각(forgetting)은 1급 메모리 연산

**Claim.** 승급(consolidation)과 망각(forgetting)은 1급 메모리 연산으로 정식화된다. 메모리 관리 = **(a)고수준 개념 요약 + (b)유사 항목 병합으로 중복 제거 + (c)불필요·오래된 기억 망각**의 세 부분으로 구성된다. Consolidation은 '단기 경험을 영속 메모리로 변환(상호작용 이력을 durable form으로 인코딩)'으로, Forgetting은 'outdated/irrelevant/harmful 콘텐츠를 선택적으로 억제'로 명시 정의된다(무한 보존 거부). Oracle 매핑: 다이제스트=요약(summarize), 일자 간 중복 제거=병합(merge), 오래된 원본 캡처 age-out=망각(forget). ~6개월 보존은 decay/deletion 정책의 직접 적용.

**근거.** 다중 1차 서베이 만장일치.
- arXiv:2404.13501: 3대 연산(writing/management/reading) + 'managed by reflecting to generate higher-level memories, merging redundant memory entries, and forgetting unimportant, early memories'; Table 3 컬럼 = Merging/Reflection/Forgetting.
- arXiv:2505.00675: 6대 연산 중 **Consolidation**('transforming short-term experiences into persistent memory ... encoding interaction histories ... into durable forms', M_t+Δt=Consolidate(M_t,E))과 **Forgetting**('selectively suppress memory content that may be outdated, irrelevant or harmful', decay-based[Ebbinghaus]+deletion-based 분류)의 정식 정의·수식 보유.
- arXiv:2512.13564 'Memory in the Age of AI Agents'(48저자 서베이): Dynamics 라이프사이클 = Formation(extraction)/Evolution(consolidation & forgetting)/Retrieval — Evolution이 승급·망각 모두 포괄, forgetting은 recency-decay/importance-threshold 휴리스틱으로 구현.
- **주의**: arXiv:2512.13564는 순수 long/short 시간분할을 '불충분'으로 명시 기각하고 factual(knowledge)/experiential(insights & skills)/working(active context)의 기능적 분류를 제안 — Oracle 분류축 설계 시 시간보다 기능을 우선 고려할 근거.

**Confidence.** high
**Vote.** claim[1] 3-0, claim[5] 3-0, claim[6] 3-0, claim[12] 3-0, claim[13] 3-0 — merged
**출처.**
- https://arxiv.org/abs/2404.13501
- https://arxiv.org/abs/2505.00675
- https://github.com/Shichun-Liu/Agent-Memory-Paper-List

**Oracle 적용.** 다이제스트=요약, 일자 간 중복 제거=병합, 오래된 원본 age-out=망각으로 3대 연산을 명시 구현하고, ~6개월 보존을 decay/deletion 정책으로 공식화한다.

---

### 3. 시간 계층(일→주→월) 요약 압축 — 롤링 재귀 vs 계층적 reflection 트리

**Claim.** 시간 계층 요약 압축으로 장기 기억을 구성하는 패턴은 **두 가지 검증된 변형**이 있다.
- **(A) 롤링/재귀 요약**: 단일 누적 요약을 LLM이 '이전 메모리 + 새 컨텍스트 + 프롬프트'로 재귀 갱신(M_i = LLM(S_i, M_{i-1}, P_m)) — 별도 벡터 저장/검색 없이 프롬프트만으로 장기 기억 구성(MemoryBank, Recursive Summarization).
- **(B) 계층적 reflection 트리**: 원본 관찰 스트림을 주기적으로 상위 reflection으로 합성하는 다층 트리(원본 로그는 보존, 그 위에 추상 계층 적층) — Generative Agents.

Oracle의 일→주→월 다이제스트는 (B) 계층적 요약-of-요약에 정확히 대응하며, 동시에 일별 다이제스트 내부는 (A) 패턴으로도 구현 가능.

**근거.**
- **(A)** arXiv:2308.15022(Recursively Summarizing, Neurocomputing 2025): 'the LLM recursively produces new memory using previous old memory and subsequent contexts' — 단일 누적 요약 재귀 갱신, '벡터/임베딩/검색 미사용, 순수 프롬프팅' 독립 2회 확인. arXiv:2404.13501이 MemoryBank를 'distill the conversations into a high-level summary of daily events ... generating daily insights'로 인용 — **'일별' 요약 압축의 실제 구현 선례**(MemoryBank는 일별→글로벌 요약의 hierarchical 구조 + Ebbinghaus 망각 동시 보유).
- **(B)** arXiv:2304.03442(Generative Agents, UIST 2023): 'synthesize those memories over time into higher-level reflections' — 원본 leaf + 추상 non-leaf의 reflection 트리, 중요도 합이 임계 초과 시(~1일 2-3회) 주기 합성, 원본 스트림+reflection 두 계층 공존.
- arXiv:2505.00675도 recursive summarization을 장기기억 Compression('reducing memory size while preserving essential information') 기법으로 인용.
- **주의**: 학계는 '재귀/롤링 요약(단일 진화 요약)'과 '계층적 요약(요약-of-요약 다단계)'을 구분한다. 서베이가 verbatim 인용한 것은 전자이며, claim 7의 'hierarchical'·일/주/월 tiering은 Oracle로의 합리적 외삽이지 서베이 직접 주장이 아니다. 또한 Generative Agents의 reflection 트리는 진짜 다층이지만 트리거가 calendar window가 아닌 importance threshold라는 점도 차이(개념적 대응, 정확한 스케줄 일치 아님).

**Confidence.** high
**Vote.** claim[2] 3-0, claim[7] 2-1, claim[17] 3-0, claim[18] 3-0, claim[19] 3-0 — merged
**출처.**
- https://arxiv.org/abs/2404.13501
- https://arxiv.org/html/2308.15022v3
- https://arxiv.org/abs/2304.03442
- https://arxiv.org/abs/2505.00675

**Oracle 적용.** 일→주→월을 (B) 계층적 요약-of-요약으로 구축하되 일별 다이제스트 내부 생성은 (A) 롤링 재귀로 처리하고, reflection 트리거를 calendar(cron) 기반으로 채택(importance threshold 대비 단순·예측가능).

---

### 4. 반복 압축의 손실 — sanitized drift, hoarding vs amnesia

**Claim.** 반복 요약 압축은 저빈도·희귀 디테일을 매 pass마다 **silently 폐기**해 'sanitized/generic' 버전으로 드리프트하며, 정작 edge case에서 실패한다. 시스템은 **'hoarding(다 저장→노이즈에 익사) vs amnesia(공격적 압축→희귀 핵심 사실 손실)'** 사이에서 진동한다. Oracle 함의: 다이제스트만 남기고 원본을 버리면 안 됨 — 원본 corpus(평문) 보존이 압축 손실의 1차 방어책이며, 다이제스트는 그 위의 검색 가능한 추상 계층으로만 취급해야 함.

**근거.** arXiv:2603.07670v1(2026-03 서베이):
- 'Each compression pass silently discards low-frequency details. After enough passes, the agent remembers a sanitized, generic version of history—precisely the kind of memory that fails on edge cases'(§4.1)
- 'Current systems oscillate between hoarding (store everything, drown in noise) and amnesia (compress aggressively, lose rare but vital facts)'(§9.1)
- **정량 근거**: 36.7배 압축 시 2,000개 구조화 사실 중 ~60%가 중요도 무관하게 복구 불가.
- 독립 코로보레이션 광범위(Towards Data Science, mem0.ai, arXiv:2604.04853 MemMachine, 2603.17781, 2601.04463 등 동일 'summarization drift' 병리 기술). 해법 제안 논문들(hierarchical DAG/progressive summarization, arXiv:2605.04050 LCM)이 문제 존재를 전제. 단일 서베이 출처지만 정량 실험+다수 독립 코로보레이션으로 confidence high.

**Confidence.** high
**Vote.** claim[9] 3-0
**출처.**
- https://arxiv.org/html/2603.07670v1

**Oracle 적용.** 원본 corpus 평문 불변 정책을 압축 손실의 1차 방어선으로 유지하고, 다이제스트는 절대 원본을 대체하지 않는 검색용 추상 계층으로만 다룬다.

---

### 5. 단기(recency)+장기(임베딩) 결합 검색 — Generative Agents 3-요소 스코어

**Claim.** 질의·검색 시 단기(recency)와 장기(임베딩) 결합의 표준은 Generative Agents의 **3-요소 가중 스코어**다: **similarity(임베딩 관련도) + recency(시간 간격, 지수 감쇠) + importance(자체 평가 중요도)**를 결합해 top-k 선택 — 관련도만으로 검색하지 않는다. 더 정교한 변형으로 ACT-R식 vector activation(temporal decay + semantic similarity + 확률적 noise)은 hard top-k가 아닌 **stochastic recall**을 구현하며, consolidation/망각도 contextual relevance + elapsed time + recall frequency의 수식으로 동적 결정한다(자주·최근 호출 항목 잔존, 오래·드물게 호출 항목 감쇠). Oracle 함의: 현 `query.py`의 임베딩 top-k + 최근순 fallback에 recency 가중치와 중요도(이미 존재하는 reaction: interesting/useful/skip) 신호를 결합하면 됨.

**근거.**
- arXiv:2404.13501이 Generative Agents 검색을 'R is implemented based on three criteria including similarity, time interval, and importance'로 정식 인용.
- 원논문 arXiv:2304.03442 확인: score = α_recency·recency + α_importance·importance + α_relevance·relevance(α=1, [0,1] 정규화); recency=시간당 0.995 지수감쇠, importance=LLM 1-10, relevance=쿼리 임베딩 코사인. 다수 독립 출처(Frontiers Psychology 2025, AWS Bedrock AgentCore, GitHub 구현) 동일 패턴 코로보레이션.
- ACM HAI 2025 'Human-Like Remembering and Forgetting in LLM Agents'(DOI 10.1145/3765766.3765803): 'vector-based activation mechanism, incorporating temporal decay, semantic similarity, and probabilistic noise to mimic natural memory dynamics' → stochastic recall. 동일 그룹 수식(arXiv:2404.00573) p_n(t)=[1-exp(-r·e^(-t/g_n))]/[1-e^(-1)] (r=관련도, t=경과시간), g_n은 호출마다 증가→감쇠 둔화로 'frequently-recalled·recently-used 잔존, stale·rarely-recalled 감쇠' 입증.
- **주의**: claim 16 quote의 출처 DOI는 CHI 2024 자매논문이나 동일 모델; decay는 절대 0 미도달(soft suppression).

**Confidence.** high
**Vote.** claim[3] 3-0, claim[15] 3-0, claim[16] 2-1 — merged
**출처.**
- https://arxiv.org/abs/2404.13501
- https://arxiv.org/abs/2304.03442
- https://dl.acm.org/doi/10.1145/3765766.3765803

**Oracle 적용.** `query.py`를 임베딩 단일 정렬에서 similarity+recency(지수감쇠)+importance(reaction interesting/useful/skip)의 3-요소 가중 스코어로 교체하는 것이 최우선 개선이다.

---

### 6. 캐노니컬 시스템/논문의 vetted 진입점

**Claim.** 참조할 캐노니컬 시스템/논문의 vetted 진입점과 각 설계 요지:
- **MemGPT/Letta**(2023/10, arXiv:2310.08560) = OS virtual-memory식 스케줄링(main context vs external context를 function call로 페이징)
- **Generative Agents**(2023/04, arXiv:2304.03442) = layered memory store + memory stream + reflection
- **Mem0**(2025/04, arXiv:2504.19413) = production용 확장형 장기 메모리
- **A-MEM**(2025/02, arXiv:2502.12110) = Zettelkasten식 agentic memory
- **Zep/Graphiti**(2025/01, arXiv:2501.13956) = temporal knowledge graph

cross-session 영속·long-horizon 일관성에는 interaction step·event snippet·timeline을 구조화 저장 후 replay하는 procedural/episodic 계층이 권장되며 external(retrieval) 메모리와 인프라 공유.

**근거.**
- arXiv:2512.13564의 공식 paper list(github.com/Shichun-Liu/Agent-Memory-Paper-List)가 5개 캐노니컬 시스템을 정확한 날짜와 함께 카탈로그, 각 arXiv ID 실재 확인.
- arXiv:2509.18868v1(Zhang et al. 서베이 2025-09): 'Generative Agents and MemGPT provide operational blueprints via layered memory stores and virtual memory-style scheduling, respectively'(MemGPT의 OS virtual-memory는 원논문 arXiv:2310.08560가 명시); 'When cross-session persistence and long-horizon behavioral consistency are required, intermediate steps, event snippets, and timelines ... stored in structured form and replayed as needed; this procedural/episodic memory emphasizes temporal structure and re-playability ... shares infrastructure with external memory'.
- **주의**: Generative Agents를 'layered memory store'로 부르는 것은 다소 느슨하다 — 실제로는 단일 sequential memory stream이고 layering은 reflection으로 창발한다(서베이 자체 표현이며 claim은 '서베이가 그렇게 기술함'만 주장).

**Confidence.** high
**Vote.** claim[10] 3-0, claim[11] 3-0, claim[14] 3-0 — merged
**출처.**
- https://github.com/Shichun-Liu/Agent-Memory-Paper-List
- https://arxiv.org/html/2509.18868v1

**Oracle 적용.** Generative Agents(reflection 계층) + MemoryBank(일별 요약·Ebbinghaus 망각)를 1차 청사진으로 삼고, 그래프/프로덕션 확장이 필요해지면 Zep/Graphiti·Mem0를 후보로 둔다.

---

### 7. Oracle 현재 아키텍처 매핑 — 구체적 개선 지점(코드 1차 확인)

**Claim.** Oracle 현재 아키텍처를 본 조사 기준으로 매핑하면 구체적 개선 지점이 드러난다(코드 1차 확인).
1. **검색**: `backend/query.py`는 임베딩 top-k(embedding.search) + 최근순 fallback뿐 — Generative Agents식 recency+importance 결합 부재; importance 신호로 쓸 reaction 필드(interesting/useful/skip)는 이미 존재.
2. **시간 계층**: `backend/digest.py`는 일별 LLM 다이제스트(digest/YYYY-MM-DD.md)는 있으나 주/월은 코드 통계 집계(index_meta, top_tags/threads_active)일 뿐 LLM 서사 요약이 아님 — 즉 '주/월 다이제스트=장기 기억 계층'은 아직 부분적으로만 구현됨, 계층적 요약-of-요약(일→주→월)은 신규 구축 영역.
3. **망각**: 원본 corpus 평문이 명시적 불변(immutable)이라 ~6개월 age-out/decay 정책이 전무 — 압축 손실 방어(원본 보존)는 이미 충족, 단기 캡처 망각·다이제스트 보존의 차등 retention은 미구현.

**근거.**
- `query.py` L52-58: hits=embedding_mod.search(question,top_k=limit); 임베딩 실패 시 db.records().find().sort('ts',-1).limit(limit) — recency·importance 가중 결합 없음, 단순 임베딩 순서 유지(L56).
- `embedding.py` L114-121: 순수 코사인 brute-force top-k(개인 규모라 numpy 충분), decay/importance 미반영.
- `digest.py`: run_daily만 LLM 다이제스트 생성(L170-176, digest/YYYY-MM-DD.md), _update_master_index(L339-417)는 월별 MongoDB index_meta에 record_count/top_tags/threads_active/types_dist를 코드 aggregate로 집계할 뿐 주/월 LLM 요약 없음 — vault 구조도 daily digest + monthly statistical index. reaction 집계(_aggregate_reactions L329-336, interesting/useful/skip)는 daily digest 프롬프트에만 쓰이고 검색 스코어엔 미반영 → importance 신호 재활용 여지. digest.py L8-9 주석: '정본 평문(corpus/)은 불변' — 망각 정책 부재 명시.

**Confidence.** high
**Vote.** parent-context grounding (코드 1차 확인, 비투표)
**출처.**
- /Users/astonlee/projects/oracle/backend/query.py
- /Users/astonlee/projects/oracle/backend/digest.py
- /Users/astonlee/projects/oracle/backend/embedding.py

**Oracle 적용.** 우선순위 = ① `query.py` 3-요소 스코어화(reaction→importance 재활용) → ② 주/월 LLM 서사 다이제스트 신규 구축(계층적 요약) → ③ 단기 캡처 vs 다이제스트 차등 retention(6개월) 도입.

---

## 주의·한계 (caveats)

- **시간 민감성**: 핵심 1차 출처가 대부분 2024-2026 arXiv 서베이이며 일부는 미래 날짜 ID(arXiv:2603.07670 '2026-03', 2512.13564 '2025-12', 2509.18868 '2025-09')로 검증되었다. 최신 분야라 정의·분류가 빠르게 진화 중이므로 **6-12개월 내 재확인 권장**.
- **분류 프레임워크 자체가 출처마다 다르다**: 시간 축(2505.00675)·상호작용 범위 축(2404.13501)·인지 4계층(2603.07670, CoALA 계보)·기능 축(2512.13564)이 공존한다. 가장 최신 대형 서베이(2512.13564, 48저자)는 순수 시간 분할(long/short)을 '불충분'으로 명시 기각했다. 따라서 'short/long-term'이라는 연구 질문의 프레이밍 자체가 학계에서는 이미 working/episodic/semantic 또는 factual/experiential/working으로 대체되는 추세이니, **Oracle 설계 시 '단기/장기'를 시간이 아닌 '원본 일화 vs 추상 의미'의 기능 축으로 재해석하는 편**이 최신 정설에 부합한다.
- **약한 지점**: claim 9(압축 손실)·claim 15·16(ACT-R 메모리)는 단일 1차 출처 기반이다(claim 9는 정량 실험+다수 독립 코로보레이션으로 보강, ACT-R은 ACM HAI/CHI 게재 + arXiv full text로 보강되었으나 ACM 본문은 paywall로 abstract·arXiv만 직접 확인). claim 7의 'hierarchical day→week→month' tiering, claim 19/2의 'Oracle 다이제스트=장기기억 재활용' 매핑은 모두 **연구자의 합리적 외삽이지 원논문 직접 주장이 아니다** — 원논문들은 대화 세션/단일 롤링 요약을 다루지 일/주/월 temporal digest 다단계를 명시하지 않는다.
- **반박된(killed) 4개 claim**: 출처를 과대 일반화하거나(예: 3개 압축전략을 서베이가 '실증'했다는 주장, 4-way 분류가 short/long에 정확 매핑된다는 주장) abstract 환각(Compression→Condensation 오독)에서 비롯 — 본 리포트는 이를 배제했다. 구체 내역:
  1. (0-3, arXiv:2603.07670v1) 서베이가 세 압축 전략(sliding window/rolling summary/hierarchical summary)을 turn/session/topic granularity로 '실증'하고 retriever가 resolution을 adaptive 선택하는 multi-granularity indexing이 최적이라 '주장'했다 — **과대 일반화**.
  2. (0-3, arXiv:2603.07670v1) Generative Agents가 recency/relevance/importance 3신호로 검색하며 reflection/consolidation 제거 시 48시뮬레이션 시간 내 coherent multi-day planning이 붕괴한다 — **원논문 미검증 인과 주장**.
  3. (0-3, arXiv:2509.18868v1) parametric/contextual-working/external-non-parametric/procedural-episodic 4-way 분류가 short/long을 contextual vs external+episodic에 '정확 매핑'한다 — **매핑 환각**.
  4. (0-3, dl.acm.org/10.1145/3765766.3765803) 'Extended Declarative Memory Module'이 semantic similarity+frequency+temporal decay+contextual relevance 4요소로 per-memory activation을 계산한다 — **abstract 오독**.
- **스케줄 불일치**: Generative Agents의 reflection 트리거는 calendar window가 아닌 importance-score threshold라 Oracle의 cron 기반 일/주/월과 정확히 일치하지 않는다(개념적 대응). MemoryBank·Recursive Summarization은 원본을 폐기하지 않고 요약과 병존시킨다는 점도 유의(Oracle도 corpus 보존하므로 정합).

---

## 미해결 질문 (openQuestions)

1. **압축 손실 방어 구조**: 일→주→월 계층적 요약에서 sanitized drift를 막으려면 각 상위 계층이 하위 원본/다이제스트로의 역참조(back-pointer)나 DAG 구조를 얼마나 유지해야 하는가? arXiv:2605.04050(LCM)·DAG 기반 progressive summarization이 해법으로 제시되나 개인 규모(MongoDB brute-force)에서의 구체적 구현·비용은 미조사.
2. **차등 retention 파라미터**: ~6개월 보존에서 단기(원본 캡처)와 장기(다이제스트)의 차등 retention 정책 — 정확히 며칠/몇 주 후 원본을 age-out하고 어떤 importance/reaction 임계로 예외 보존할지의 정량 기준(decay 상수, threshold)은 시스템마다 ad-hoc 휴리스틱이라 Oracle 맞춤 튜닝 필요. ACT-R의 g_n 갱신식이 출발점이 될 수 있으나 캡처 빈도가 낮은 일상 데이터에 맞는 파라미터는 미정.
3. **multi-resolution 검색 라우팅**: 검색 시 일/주/월 다이제스트 계층과 원본 record 임베딩을 어떻게 라우팅할 것인가 — 광범위/요약형 질의는 상위 다이제스트로, 특정 사실 질의는 원본 임베딩으로 보내는 multi-resolution 라우팅이 이상적이나(반박된 claim의 'adaptive resolution selection'은 서베이가 실증하진 않음), 실제로 검증된 구현 패턴·정확도는 추가 조사 필요.
4. **reaction↔importance 융합**: reaction 신호(interesting/useful/skip)를 Generative Agents의 importance(LLM 1-10 자체평가)와 어떻게 결합/정규화해 단일 importance 스코어로 만들 것인가, 그리고 사용자 명시 reaction이 없는 다수 record의 importance를 LLM이 사후 평가하게 할지(비용·일관성 trade-off)는 미해결.

---

## 참조 출처

24개 출처 fetch. quality 등급(primary > secondary > blog)과 조사 앵글 포함.

| # | Title / 식별 | URL | Quality | Angle |
|---|---|---|---|---|
| 1 | arXiv:2404.13501 (ACM TOIS 서베이) | https://arxiv.org/abs/2404.13501 | primary | broad/primary - 분류와 consolidation/forgetting |
| 2 | arXiv:2505.00675 (Du et al. 2025) | https://arxiv.org/abs/2505.00675 | primary | broad/primary - 분류와 consolidation/forgetting |
| 3 | arXiv:2603.07670v1 (2026 서베이, 인지 4계층) | https://arxiv.org/html/2603.07670v1 | primary | broad/primary - 분류와 consolidation/forgetting |
| 4 | arXiv:2509.18868v1 (Zhang et al. 서베이) | https://arxiv.org/html/2509.18868v1 | primary | broad/primary - 분류와 consolidation/forgetting |
| 5 | Agent-Memory-Paper-List (2512.13564 공식 list) | https://github.com/Shichun-Liu/Agent-Memory-Paper-List | primary | broad/primary - 분류와 consolidation/forgetting |
| 6 | ACM HAI 2025 'Human-Like Remembering and Forgetting' | https://dl.acm.org/doi/10.1145/3765766.3765803 | primary | broad/primary - 분류와 consolidation/forgetting |
| 7 | arXiv:2304.03442 (Generative Agents, UIST 2023) | https://arxiv.org/abs/2304.03442 | primary | academic/technical - 시간 계층 요약 압축 |
| 8 | arXiv:2308.15022v3 (Recursively Summarizing) | https://arxiv.org/html/2308.15022v3 | primary | academic/technical - 시간 계층 요약 압축 |
| 9 | Engineers of AI — Memory Compression & Summarization | https://engineersofai.com/docs/agentic-ai/agent-memory/memory-compression-and-summarization | blog | academic/technical - 시간 계층 요약 압축 |
| 10 | LangChain — Time-weighted Vectorstore | https://python.langchain.com/v0.2/docs/how_to/time_weighted_vectorstore/ | primary | implementation - recency·벡터 하이브리드 |
| 11 | ar5iv mirror — Generative Agents | https://ar5iv.labs.arxiv.org/html/2304.03442 | primary | implementation - recency·벡터 하이브리드 |
| 12 | OpenSearch — Reciprocal Rank Fusion Hybrid Search | https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/ | secondary | implementation - recency·벡터 하이브리드 |
| 13 | Hybrid Retrieval RRF Rank Fusion (blog) | https://avchauzov.github.io/blog/2025/hybrid-retrieval-rrf-rank-fusion/ | blog | implementation - recency·벡터 하이브리드 |
| 14 | arXiv:2501.13956v1 (Zep/Graphiti) | https://arxiv.org/html/2501.13956v1 | primary | implementation - recency·벡터 하이브리드 |
| 15 | mem0.ai — RAG vs AI Memory | https://mem0.ai/blog/rag-vs-ai-memory | blog | implementation - recency·벡터 하이브리드 |
| 16 | arXiv:2304.03442 (PDF, Generative Agents) | https://arxiv.org/pdf/2304.03442 | primary | comparative/deep-dive - 오픈소스·논문 설계 |
| 17 | arXiv:2310.08560 (PDF, MemGPT) | https://arxiv.org/pdf/2310.08560 | primary | comparative/deep-dive - 오픈소스·논문 설계 |
| 18 | arXiv:2504.19413v1 (Mem0) | https://arxiv.org/html/2504.19413v1 | primary | comparative/deep-dive - 오픈소스·논문 설계 |
| 19 | arXiv:2502.12110 (A-MEM, Zettelkasten) | https://arxiv.org/abs/2502.12110 | primary | comparative/deep-dive - 오픈소스·논문 설계 |
| 20 | MongoDB — TTL Index | https://www.mongodb.com/docs/manual/core/index-ttl/ | primary | practitioner - MongoDB·retention/TTL |
| 21 | MongoDB Atlas — Vector Search Stage | https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/ | primary | practitioner - MongoDB·retention/TTL |
| 22 | MongoDB Atlas — Hybrid Search | https://www.mongodb.com/docs/atlas/atlas-vector-search/hybrid-search/ | primary | practitioner - MongoDB·retention/TTL |
| 23 | MongoDB — Long-Term Memory for Agents (LangGraph) | https://www.mongodb.com/company/blog/product-release-announcements/powering-long-term-memory-for-agents-langgraph | primary | practitioner - MongoDB·retention/TTL |
| 24 | Google Cloud Medium — Tiered Agentic Memory | https://medium.com/google-cloud/mastering-ais-mind-designing-tiered-agentic-memory-for-llms-4b747afb62c9 | blog | practitioner - MongoDB·retention/TTL |

*추가로 본문에서 인용된 보조 출처(투표 출처에는 미포함): arXiv:2512.13564 (Memory in the Age of AI Agents, 48저자 서베이), arXiv:2309.02427 (CoALA), arXiv:2404.00573 (ACT-R 자매논문), arXiv:2605.04050 (LCM), arXiv:2604.04853 (MemMachine).*
