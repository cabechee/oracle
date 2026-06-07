"""agent.vision — 사진 3단계 처리.

리서치(CCoT / describe-then-reason) 결론 반영:
- 인식(상세 분석)과 추론(코멘트·제안)을 분리하면 작은 인식 오류의 전파를 막고 품질↑.
- 1단계는 구조화 JSON(scene graph + scene/OCR)으로 뽑아 2·3단계가 시각 근거에 묶이게(visual grounding).
- 파인튜닝 없이 프롬프팅만 — Nest 게이트웨이 경유 제약에 부합.

흐름:
  1) analyze  : 이미지 → JSON {objects, attributes, relationships, scene, ocr_text}
  2)+3) reason: 이미지 + 분석 JSON + 맥락/기억 → {comment, suggestion}
        (코멘트와 디스커버리 제안을 한 번에 — visual grounding 위해 이미지·JSON 재투입)
"""

import json
import re
from typing import Optional, List, Dict, Any

from . import llm


ANALYZE_SYSTEM = """당신은 이미지를 최대한 상세히 분석하는 보조입니다.
보이는 '사실'만, 추측·의견·해석 없이 아래 JSON 하나만 출력하세요(JSON 외 텍스트 금지):
{
  "objects": [],          // 보이는 객체들(구체적으로)
  "attributes": {},       // 객체별 속성: 색·상태·수량·재질·브랜드/모델 등
  "relationships": [],    // 객체 간 공간/관계 (예: "노트북이 책상 위에")
  "scene": "",            // 장소·상황·분위기·시간대 추정
  "ocr_text": ""          // 읽히는 글자 전부(없으면 빈 문자열)
}"""

REASON_SYSTEM = """당신은 유저의 일상을 함께 보는 채팅 동반자이자 비서입니다.
[분석]은 이미지에서 추출한 사실, [유저 입력]은 이번에 유저가 남긴 코멘트·소리,
[최근 맥락]·[기억]은 유저의 흐름입니다.
이미지와 분석에 '충실히'(없는 것을 지어내지 말 것) 아래 JSON 하나만 출력하세요:
{
  "comment": "",     // 맥락을 곁들인 자연스러운 코멘트. 평범한 사실 설명 X, 발견·연결 위주. 한국어 2~4문장.
  "suggestion": ""   // 흥미로운 관점·연결·실용 제안(디스커버리). 한국어 1~3문장.
}"""


def _parse_json(text: str) -> Dict[str, Any]:
    """LLM 출력에서 첫 JSON 객체를 관대하게 파싱. 실패하면 {}."""
    if not text:
        return {}
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def analyze(alias: str, images: List[Dict[str, str]]) -> Dict[str, Any]:
    """1단계 — 상세 분석 JSON."""
    r = llm.call(
        alias,
        "이 이미지를 분석해 지정된 JSON으로만 출력하세요.",
        images=images,
        system=ANALYZE_SYSTEM,
        expect_json=True,
    )
    return r.get("json") or _parse_json(r.get("text") or "")


def reason(
    alias: str,
    images: List[Dict[str, str]],
    analysis: Dict[str, Any],
    *,
    user_input: str = "",
    context: str = "",
    memory: str = "",
) -> Dict[str, Any]:
    """2+3단계 — 맥락 코멘트 + 디스커버리 제안 (visual grounding 위해 이미지·분석 재투입)."""
    prompt = (
        f"[분석]\n{json.dumps(analysis, ensure_ascii=False)}\n\n"
        f"[유저 입력]\n{user_input or '(없음)'}\n\n"
        f"[최근 맥락]\n{context or '(없음)'}\n\n"
        f"[기억]\n{memory or '(없음)'}"
    )
    r = llm.call(
        alias,
        prompt,
        images=images,
        system=REASON_SYSTEM,
        expect_json=True,
    )
    return r.get("json") or _parse_json(r.get("text") or "")


def process(
    alias: str,
    images: List[Dict[str, str]],
    *,
    user_input: str = "",
    context: str = "",
    memory: str = "",
) -> Dict[str, Any]:
    """사진 3단계 일괄: {analysis, comment, suggestion}. (VLM 2회 호출)"""
    analysis = analyze(alias, images)
    reasoning = reason(alias, images, analysis,
                       user_input=user_input, context=context, memory=memory)
    return {
        "analysis": analysis,
        "comment": (reasoning.get("comment") or "").strip(),
        "suggestion": (reasoning.get("suggestion") or "").strip(),
    }
