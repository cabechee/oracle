"""agent.companion — 위치·시간 이벤트에 쿠키/베르가 거는 한마디.

폰이 백그라운드에서 집/작업실 도착·이탈·500m 이탈·정시 등을 감지하면 이 API를
호출, 쿠키(오목눈이) 또는 베르(강아지) 중 랜덤으로 짧게 말을 건다(알림으로 표시).
페르소나는 personas(어드민 편집) 재사용 — 여기엔 인격 로직을 쌓지 않는다.
"""

import random
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

import db
import companion_config as cc   # 말 걸기 정책(텀·조용구간·이벤트 on/off) — 어드민 설정
import places as places_mod      # 장소 설명(맥락) — 도착 멘트가 그곳을 알게
from . import llm
from . import personas   # 베르/쿠키 정체성 — 어드민(/admin)에서 수정
from config import task_alias

# 폰(geofence/타이머)이 event만 보낸다. 위치 이벤트는 장소 타입으로 쪼개지 않고
# '저장된 장소 도착/나섬' 둘로 — 장소 이름·설명은 레지스트리(places)에서 보강해 LLM이 알아서.
_ARRIVE = {"arrive_place", "arrive_home", "arrive_office"}   # 레거시 포함
_LEAVE = {"leave_place", "leave_visit", "leave_home", "leave_office"}


def _situation(event: str, place: Optional[str], minutes: Optional[int]) -> str:
    """이벤트 + 장소(이름/kind) → LLM에 줄 상황 한 줄. 저장된 곳이면 이름·설명을 녹인다."""
    info = None
    if place:
        try:
            info = places_mod.lookup(place)
        except Exception:
            info = None
    if event in _ARRIVE:
        if info:
            s = f"아빠가 '{info['name']}'에 도착해서 머물기 시작했어."
            if (info.get("description") or "").strip():
                s += f" (거기에 대해 내가 아는 것: {info['description'].strip()})"
        else:
            s = "아빠가 아직 저장 안 한 새로운 곳에 도착해서 좀 머무르기 시작했어. 여기가 어딘지·뭐 하는지 궁금해."
    elif event in _LEAVE:
        if info:
            s = f"아빠가 '{info['name']}'에서 나서 다시 움직이기 시작했어."
            if (info.get("description") or "").strip():
                s += f" (거기: {info['description'].strip()})"
        else:
            s = "아빠가 한동안 머물던 곳에서 나서 다시 움직이기 시작했어."
    elif event == "checkin":
        s = "지금 아빠가 뭐 하고 있을까, 문득 궁금해졌어."
    else:
        s = "아빠한테 가볍게 말 걸고 싶어."
    if minutes:
        s += f" (그곳에 약 {minutes}분 있었어)"
    return s


def say(event: str, place: Optional[str] = None,
        speaker: Optional[str] = None,
        minutes: Optional[int] = None) -> Dict[str, Any]:
    """이벤트에 맞춰 쿠키/베르 중 하나가 거는 한마디. speaker 미지정이면 랜덤.

    반환: {speaker: "쿠키"|"베르", text, alias}. 미설정/실패/게이팅이면 text="".
    """
    now = datetime.now()
    kind = cc.kind_of(event)
    # 지금 말 걸 타이밍인가 — 마스터·새벽 조용구간·활동 시간대·텀/쿨다운·이벤트 on/off.
    # (LLM 호출 전에 막으므로 억제될 땐 비용 0. 빈 text → 폰이 알림 안 띄움)
    if not cc.event_enabled(event) or not cc.should_speak(kind, now):
        return {"speaker": "", "text": "", "alias": "", "gated": True}

    ctx = _situation(event, place, minutes)
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
    # 실제 맥락(쌓인 신호·오늘 기록/방문·시간대) — 자연스러우면 하나만 슬쩍 녹이게.
    real_ctx = cc.gather_context(now)
    ctx_block = (
        f"[요즘 상황 — 이 중 자연스러운 게 있으면 하나만 슬쩍 녹여도 좋아. 다 나열하지 말고, "
        f"억지로 엮지 말고, 없으면 그냥 가볍게.]\n{real_ctx}\n\n" if real_ctx else "")
    prompt = (
        "지금은 네가 **먼저** 아빠에게 톡 말을 거는 상황이야. 아빠가 너한테 무슨 말을 한 게 "
        "아니라(아빠는 아직 아무 말도 안 했어), 아빠 생각이 나서 네가 문득 말 거는 거야.\n\n"
        f"[계기] {ctx}\n\n"
        f"{ctx_block}"
        "이 상황에 맞춰 아빠에게 짧게 말 걸어 — 한 문장, 길어도 두 문장. 자연스럽고 가볍게, "
        f"부담 주지 말고. {tone} 인사·이름표 없이 그 한마디만.")
    try:
        r = llm.call(alias, prompt, system=system)
        text = (r.get("text") or "").strip()
        if text:
            cc.mark_spoken(kind, now)   # 텀/쿨다운 기준 시각 갱신 (빈 응답엔 안 함)
        return {"speaker": name, "text": text, "alias": alias}
    except Exception as e:
        print(f"[companion] say 실패: {e}", flush=True)
        return {"speaker": name, "text": "", "alias": alias}


def _ts_to_dt(ts: Any) -> datetime:
    """epoch ms(int) | ISO(str) | None → datetime. 실패하면 now."""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000.0)
        except (ValueError, OSError, OverflowError):
            return datetime.now()
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return datetime.now()
    return datetime.now()


def record_asked(speaker: str, text: str, ts: Any = None) -> Dict[str, Any]:
    """동반자가 먼저 건 말을 흐름(conversations)에 남긴다 — 아빠가 '기록'으로 답할 때 호출.

    ts = 아빠가 알림을 탭해 들어온 순간(epoch ms). 보낸 시각이 아니라 '답하러 들어온' 순간이라,
    흐름에서 그 답한 기록 바로 위에 자연스럽게 얹힌다. 대화 응답과 구분하려 companion=True.
    반환: 앱이 흐름에 바로 꽂을 메시지(ChatMessage shape).
    """
    when = _ts_to_dt(ts)
    doc = {
        "_id": f"cmsg-{when.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "role": "assistant",
        "text": (text or "").strip(),
        "ts": when,
        "referenced": [],
        "speaker": (speaker or "").strip(),   # 베르 | 쿠키
        "companion": True,                    # 선제 말걸기 (대화 응답과 구분)
    }
    db.conversations().insert_one(doc)
    out = dict(doc)
    out["ts"] = when.isoformat()
    return out
