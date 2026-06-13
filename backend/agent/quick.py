"""agent.quick — 쿠키(오목눈이)의 빠른 1차 반응.

모든 캡처(텍스트·사진)가 메인 디스커버리(베르) 전에 이걸 먼저 거친다.
haiku로 몇 초 안에 짧은 한마디 → record.quick. 폰은 폴링으로 이걸 먼저 본다.
(액션 감지 — 타이머 등 — 도 추후 이 빠른 트랙에 얹는다.)
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any

from . import llm
from . import personas   # 쿠키 페르소나 — 어드민(/admin)에서 수정


def _loads(text: Optional[str]) -> Any:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def _valid_action(a: Any) -> Optional[Dict[str, Any]]:
    """LLM이 낸 action 검증 — timer(seconds 1~86400)만 통과."""
    if not isinstance(a, dict) or a.get("tool") != "timer":
        return None
    try:
        sec = int(a.get("seconds"))
    except (TypeError, ValueError):
        return None
    if not (0 < sec <= 86400):
        return None
    return {"tool": "timer", "seconds": sec,
            "label": str(a.get("label") or "").strip()}


# 액션 감지 — 쿠키 한마디(페르소나)와 분리. 순수 JSON이라 작은 모델도 형식을 잘 따름.
# 검색은 안 함(느리고 마이너 제품엔 부정확) — 빠른 추정값 + 사용자가 시계앱에서 조정.
ACTION_SYSTEM = """입력(사진·영상·메모)에 '시간이 걸리는 일'이 있으면 타이머를 제안하는 도구입니다.
대상: 라면·계란·파스타·차·면 등 끓이거나 익히거나 일정 시간 기다리는 것.

seconds는 빠르게 추정하세요(검색하지 말 것). 우선순위:
1. ★최우선★ 사진에 조리법·조리시간 텍스트가 보이면(예: "조리시간 4분", "4분간 끓여주세요",
   "물 550ml에 4분") 그 분/초를 그대로 읽어 seconds로. 봉지 뒷면·조리예를 찍은 거면 이게 가장 정확.
2. 텍스트가 안 보이고 아는 제품이면 알려진 값(신라면 270, 진라면 240, 너구리 300, 안성탕면 240).
3. 모르는 라면·일반 조리면 통상값 270. 반숙 390·완숙 600·파스타 600·차 180.
사용자가 시계앱에서 최종 조정하므로 대략이면 됩니다. label에 제품명·음식 종류.

해당 없으면 tool은 null. 아래 JSON 하나만 출력(JSON 외 텍스트 금지):
{"tool": null}  또는  {"tool": "timer", "seconds": 270, "label": "탱글"}"""


def say(alias: str, user_input: str = "",
        media: Optional[List[Dict[str, str]]] = None) -> str:
    """쿠키의 짧은 한마디 (페르소나). 멀티모달 전제."""
    body = user_input.strip() or "(미디어만 있고 글은 없음)"
    r = llm.call(alias, f"[방금 들어온 것]\n{body}\n\n쿠키답게 짧게 한마디.",
                 images=media or None, system=personas.quick_system())
    return (r.get("text") or "").strip()


def react(
    alias: str,
    user_input: str = "",
    images: Optional[List[Dict[str, str]]] = None,
    audio: Optional[List[Dict[str, str]]] = None,
    video: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """쿠키 한마디 + 액션 감지를 병렬 호출 (속도). 반환: {text, action}."""
    media = (images or []) + (audio or []) + (video or [])
    body = user_input.strip() or "(미디어만 있고 글은 없음)"
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_say = ex.submit(say, alias, user_input, media or None)
        f_act = ex.submit(detect_action, alias, body, media or None)
        return {"text": f_say.result(), "action": f_act.result()}


def detect_action(alias: str, body: str,
                  media: Optional[List[Dict[str, str]]] = None) -> Optional[Dict[str, Any]]:
    """시간 액션 감지 — 타이머만. 미디어(사진 등)도 보고 판단, 제품이면 검색."""
    try:
        r = llm.call(alias, f"[입력]\n{body}\n\n시간이 걸리는 일이면 타이머 JSON, 아니면 tool=null.",
                     images=media or None, system=ACTION_SYSTEM, expect_json=True)
        data = r.get("json") or _loads(r.get("text")) or {}
        return _valid_action(data)
    except Exception:
        return None
