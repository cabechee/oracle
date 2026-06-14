"""agent.companion — 위치·시간 이벤트에 쿠키/베르가 거는 한마디.

폰이 백그라운드에서 집/작업실 도착·이탈·500m 이탈·정시 등을 감지하면 이 API를
호출, 쿠키(오목눈이) 또는 베르(강아지) 중 랜덤으로 짧게 말을 건다(알림으로 표시).
페르소나는 personas(어드민 편집) 재사용 — 여기엔 인격 로직을 쌓지 않는다.
"""

import random
from typing import Optional, Dict, Any

from . import llm
from . import personas   # 베르/쿠키 정체성 — 어드민(/admin)에서 수정
from config import task_alias

# 이벤트 → LLM에 줄 상황 설명. 폰(geofence/타이머)이 판정해 event만 보낸다.
_EVENTS = {
    "arrive_home":   "아빠가 방금 집에 도착했어.",
    "arrive_office": "아빠가 방금 작업실(스튜디오)에 도착했어.",
    "leave_home":    "아빠가 집에서 나가 어디론가 가고 있어.",
    "leave_office":  "아빠가 작업실에서 나섰어.",
    "deviate":       "아빠가 평소 있던 곳에서 500m 넘게 벗어나 어디론가 이동 중이야.",
    "checkin":       "지금 아빠가 뭐 하고 있을까, 문득 궁금해졌어.",
}


def say(event: str, place: Optional[str] = None,
        speaker: Optional[str] = None) -> Dict[str, Any]:
    """이벤트에 맞춰 쿠키/베르 중 하나가 거는 한마디. speaker 미지정이면 랜덤.

    반환: {speaker: "쿠키"|"베르", text, alias}. 미설정/실패면 text="".
    """
    ctx = _EVENTS.get(event) or "아빠한테 가볍게 말 걸고 싶어."
    if place:
        ctx += f" (장소: {place})"
    who = speaker if speaker in ("cookie", "berr") else random.choice(["cookie", "berr"])
    if who == "cookie":
        system = personas.current("cookie_identity")
        alias = task_alias("quick") or task_alias("insight")
        name = "쿠키"
        tone = "넌 반말로 짧고 발랄하게, 살짝 장난스럽게 툭 건네 (존댓말·'요' 금지)."
    else:
        system = personas.current("berr_identity")
        alias = task_alias("insight") or task_alias("quick")
        name = "베르"
        tone = "넌 존댓말로 다정하고 차분하게, 애교 있게 건네."
    if not alias:
        return {"speaker": name, "text": "", "alias": ""}
    prompt = (
        "지금은 네가 **먼저** 아빠에게 톡 말을 거는 상황이야. 아빠가 너한테 무슨 말을 한 게 "
        "아니라(아빠는 아직 아무 말도 안 했어), 아빠 생각이 나서 네가 문득 말 거는 거야.\n\n"
        f"[상황] {ctx}\n\n"
        "이 상황에 맞춰 아빠에게 짧게 말 걸어 — 한 문장, 길어도 두 문장. 자연스럽고 가볍게, "
        f"부담 주지 말고. {tone} 인사·이름표 없이 그 한마디만.")
    try:
        r = llm.call(alias, prompt, system=system)
        return {"speaker": name, "text": (r.get("text") or "").strip(), "alias": alias}
    except Exception as e:
        print(f"[companion] say 실패: {e}", flush=True)
        return {"speaker": name, "text": "", "alias": alias}
