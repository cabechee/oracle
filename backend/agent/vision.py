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
}
규칙:
- 사진이 여러 장이면 모두 같은 장면·순간의 일부다. 전부 종합해 하나의 JSON으로 합쳐 분석하세요(장면별로 나누지 말 것).
- 확실하지 않은 건 추측으로 채우지 말 것 — 안 보이면 비워두고, 추정이 필요한 값은 "추정: " 접두를 붙이세요.
- 브랜드·모델·글자는 실제로 읽히거나 식별 가능할 때만. 비슷해 보인다고 단정 금지.
- 틀린 한 줄이 이후 모든 단계에 전파됩니다 — 적게 쓰더라도 정확하게."""

from . import personas   # 베르 페르소나 — 어드민(/admin)에서 수정


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


def analyze(alias: str, images: List[Dict[str, str]],
            user_input: str = "") -> Dict[str, Any]:
    """1단계 — 상세 분석 JSON. 아빠가 사진에 덧붙인 코멘트/소리/EXIF가 있으면 함께 본다.

    코멘트는 보통 사진의 식별 단서(브랜드·관계·장소·상황)를 담으므로 분석 정확도에 직접
    기여한다. 단 system(ANALYZE_SYSTEM)의 '보이는 사실만' 원칙은 유지 — 코멘트는 참고이되
    사진에서 확인 안 되는 것을 ocr_text·objects에 사실처럼 넣지 않는다.
    """
    prompt = "이 이미지를 분석해 지정된 JSON으로만 출력하세요."
    if user_input.strip():
        prompt += (
            "\n\n[참고 — 아빠가 이 사진에 덧붙인 말·소리·정보]\n"
            + user_input.strip()
            + "\n위 정보를 분석에 반영하되(특히 브랜드·제품명·관계·장소 단서), "
            "사진에서 직접 확인되지 않는 것은 지어내지 말 것."
        )
    r = llm.call(
        alias,
        prompt,
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
        f"[최근 맥락 — 참고만, 지금 사진과 직접 이어질 때만 쓰고 아니면 무시]\n{context or '(없음)'}\n\n"
        f"[기억]\n{memory or '(없음)'}"
    )
    r = llm.call(
        alias,
        prompt,
        images=images,
        system=personas.reason_system(),
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
    """사진 3단계 일괄: {analysis, comment, suggestion}. (VLM 2회 호출)

    2단계(reason)가 실패해도 1단계 분석은 보존 — 호출자는 comment 빈 값으로
    실패를 인지하고, record/vault에는 분석이라도 남는다.
    """
    analysis = analyze(alias, images, user_input=user_input)
    try:
        reasoning = reason(alias, images, analysis,
                           user_input=user_input, context=context, memory=memory)
    except Exception as e:
        print(f"[vision] reason 실패 — 분석만 보존: {e}", flush=True)
        reasoning = {}
    return {
        "analysis": analysis,
        "comment": (reasoning.get("comment") or "").strip(),
        "suggestion": (reasoning.get("suggestion") or "").strip(),
    }


RECEIPT_SYSTEM = """이미지가 영수증·카드전표·거래내역서면 정보를 뽑아 JSON으로, 아니면 is_receipt false.
보이는 것만 채우고 없는 값은 생략(추측 금지).
{
  "is_receipt": true,
  "merchant": "가맹점/상호명",
  "total": 12000,            // 총 결제(합계) 금액 — 숫자만
  "items": ["아메리카노", "샌드위치"],   // 품목(보이면)
  "date": "2026-06-21",      // 영수증 날짜(YYYY-MM-DD, 보이면)
  "method": "현대카드",       // 결제수단(카드사·페이 등, 보이면)
  "approval": "12345678"     // 승인번호(approval no, 보이면 숫자만)
}
영수증/전표/거래내역이 아니면 {"is_receipt": false} 만 출력."""


def extract_receipt(alias: str, images: List[Dict[str, str]]) -> Dict[str, Any]:
    """이미지에서 영수증/전표 정보 추출 — 가계부용. 영수증 아니면 {is_receipt: false}."""
    if not alias or not images:
        return {"is_receipt": False}
    try:
        r = llm.call(alias, "이 이미지가 영수증/카드전표/거래내역이면 정보를 JSON으로 뽑아줘.",
                     images=images, system=RECEIPT_SYSTEM, expect_json=True)
        out = r.get("json") or _parse_json(r.get("text") or "")
        return out if isinstance(out, dict) else {"is_receipt": False}
    except Exception as e:
        print(f"[vision] 영수증 추출 실패: {e}", flush=True)
        return {"is_receipt": False}


RECEIPTS_SYSTEM = """이미지에서 영수증·카드전표·거래내역을 **전부** 찾아 각각 JSON으로.
한 장에 여러 건이 있으면 모두(묶음 영수증·여러 장 스캔 등). 보이는 것만 채우고 추측 금지.
{"receipts": [
  {"merchant": "상호명", "total": 12000, "items": ["아메리카노"], "date": "2026-06-21",
   "method": "현대카드", "approval": "12345678"}
]}
영수증이 하나도 없으면 {"receipts": []}. total(합계 금액)이 없는 건 빼라.
approval(승인번호)은 보이면 숫자만 넣어라(없으면 생략)."""


def extract_receipts(alias: str, images: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """이미지에서 영수증을 **전부** 추출 — 묶음/여러 건 지원. [{merchant,total,items,date,method}, ...]."""
    if not alias or not images:
        return []
    try:
        r = llm.call(alias, "이미지에서 영수증/전표를 전부 찾아 JSON으로 뽑아줘.",
                     images=images, system=RECEIPTS_SYSTEM, expect_json=True)
        out = r.get("json") or _parse_json(r.get("text") or "")
        recs = out.get("receipts") if isinstance(out, dict) else None
        if not isinstance(recs, list):
            return []
        return [x for x in recs if isinstance(x, dict) and x.get("total")]
    except Exception as e:
        print(f"[vision] 영수증(복수) 추출 실패: {e}", flush=True)
        return []
