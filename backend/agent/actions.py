"""대화 액션 — 자연어에서 실행 가능한 행동(현재: 캘린더 일정 등록) 감지·추출.

설계: 흐름의 한 메시지를 보고 '일정 넣어줘' 류면 이벤트를 뽑아 **제안(proposed)** 으로
돌려준다. 실제 생성은 사용자가 확인(넣기)할 때(actions.confirm). expect_json 한 번이라
tool-use 미지원 Nest에서 지금 작동하고, 추후 진짜 tool use/MCP로 승격 가능(스키마만 이동).
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, Optional

import gcal
from config import task_alias

from . import llm

# 일정 관련 신호 — 이 중 하나라도 있어야 추출 LLM 호출(매 메시지 비용 방지).
_CAL_HINT = re.compile(
    r"일정|예약|미팅|약속|회의|캘린더|스케줄|모임|행사|등록|넣어|잡아|추가|리마인드")

_SYSTEM = (
    "너는 사용자의 한국어 메시지가 '구글 캘린더에 일정을 새로 등록'하려는 요청인지 "
    "판단하고, 맞으면 이벤트를 추출하는 도우미다.\n"
    "- 명백히 일정/약속/예약을 **추가·등록**하려 할 때만 is_event=true.\n"
    "- 단순 질문·잡담·과거 회상·'일정 뭐 있어?' 같은 조회는 is_event=false.\n"
    "- 상대 날짜(오늘/내일/모레/다음주 화요일 등)는 주어진 '지금'을 기준으로 "
    "절대 시각(KST, +09:00)으로 변환.\n"
    "- 종료시각 없으면 시작 1시간 뒤. 시간 없이 날짜만이면 all_day=true.\n"
    "- title은 핵심만 짧게(예: '치과 예약', '팀 회의').\n"
    "JSON 하나만 출력:\n"
    '{"is_event": bool, "title": str, '
    '"start": "YYYY-MM-DDTHH:MM:SS+09:00", "end": str|null, '
    '"all_day": bool, "location": str}')

_WK = "월화수목금토일"


def detect_calendar(message: str,
                    now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """일정 등록 요청이면 제안 액션 dict, 아니면 None. (확인 전 — 생성 안 함)"""
    msg = (message or "").strip()
    if not msg or not _CAL_HINT.search(msg):
        return None
    alias = task_alias("chat") or task_alias("query") or task_alias("signals")
    if not alias:
        return None
    now = now or datetime.now()
    prompt = (f"[지금] {now.strftime('%Y-%m-%d')} ({_WK[now.weekday()]}) "
              f"{now.strftime('%H:%M')} KST\n[메시지] {msg}\n\n"
              "위 메시지를 판단·추출해 JSON으로.")
    try:
        r = llm.call(alias, prompt, system=_SYSTEM, expect_json=True)
        data = r.get("json") or _loads(r.get("text"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("is_event"):
        return None
    title = str(data.get("title") or "").strip()
    start = str(data.get("start") or "").strip()
    if not title or not start:
        return None
    all_day = bool(data.get("all_day"))
    end = str(data.get("end")).strip() if data.get("end") else None
    return {
        "type": "create_event",
        "status": "proposed",
        "event": {"title": title, "start": start, "end": end,
                  "all_day": all_day, "location": str(data.get("location") or "").strip()},
        "preview": _preview(title, start, all_day),
    }


def _preview(title: str, start: str, all_day: bool) -> str:
    """확인 카드용 한 줄 — '6/19(목) 15:00 · 치과 예약'."""
    try:
        d = datetime.fromisoformat(start.replace("Z", "+00:00"))
        when = f"{d.month}/{d.day}({_WK[d.weekday()]})"
        if not all_day:
            when += f" {d.strftime('%H:%M')}"
    except Exception:
        when = start
    return f"{when} · {title}"


def run(action: Dict[str, Any]) -> Dict[str, Any]:
    """확인된 액션 실행 — 현재는 create_event. 반환 {ok, event?, reason?}."""
    if (action or {}).get("type") != "create_event":
        return {"ok": False, "reason": "지원하지 않는 액션"}
    ev = action.get("event") or {}
    created = gcal.create_event(
        ev.get("title", ""), ev.get("start", ""), ev.get("end"),
        location=ev.get("location", ""), all_day=bool(ev.get("all_day")))
    if created is None:
        return {"ok": False, "reason": "캘린더 미인증 또는 생성 실패"}
    return {"ok": True, "event": created}


def _loads(text: Optional[str]) -> Any:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None
