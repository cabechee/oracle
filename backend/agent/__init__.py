"""agent — Oracle의 LLM 허브.

모든 LLM 호출·사진 처리·메모리·대화·도구를 여기로 모은다.
- llm:     Nest 게이트웨이 단일 통로 (캐싱·모델선택 hook)
- vision:  사진 3단계 (상세분석 → 맥락 코멘트 → 디스커버리 제안)
- (예정) memory / chat / tools
"""
