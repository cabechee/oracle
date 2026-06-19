"""agent.companion — 위치·시간 이벤트에 쿠키/베르가 거는 한마디.

폰이 백그라운드에서 집/작업실 도착·이탈·500m 이탈·정시 등을 감지하면 이 API를
호출, 쿠키(오목눈이) 또는 베르(강아지) 중 랜덤으로 짧게 말을 건다(알림으로 표시).
페르소나는 personas(어드민 편집) 재사용 — 여기엔 인격 로직을 쌓지 않는다.
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

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
    elif event == "park":
        s = ("아빠가 방금 차에서 내려 주차했어. 어디에 세웠는지·몇 층 몇 구역인지 사진이나 "
             "메모로 기록해두면 나중에 차 찾기 쉬우니, 기록해두겠냐고 가볍게 물어봐.")
    elif event == "askplace":
        s = ("아빠가 저장 안 된 새로운 곳에 와서 15분 넘게 머무는 중이야. 여기가 어디인지·뭐 "
             "하는 곳인지 가볍게 물어봐 — '아빠 왔다'처럼 반기지 말고(여긴 우리 집이 아니야), "
             "자주 오는 곳이면 기억해둘 수 있게 호기심으로. 답해주면 그 장소를 저장해둘게.")
    elif event == "checkin":
        s = "지금 아빠가 뭐 하고 있을까, 문득 궁금해졌어."
    else:
        s = "아빠한테 가볍게 말 걸고 싶어."
    if minutes:
        s += f" (그곳에 약 {minutes}분 있었어)"
    return s


def _speak(kind: str, situation: str,
           speaker: Optional[str] = None) -> Dict[str, Any]:
    """게이팅 통과 시 쿠키/베르 중 하나가 situation에 맞춰 거는 한마디(아빠한테 직접).

    say()·car_departure()·car_parking()의 공통 코어 — 페르소나/말투/맥락/LLM 호출.
    반환: {speaker, text, alias}. 미설정/실패/게이팅이면 text="".
    """
    now = datetime.now()
    # 지금 말 걸 타이밍인가 — 마스터·새벽 조용구간·텀/쿨다운. (LLM 전에 막아 억제 시 비용 0)
    if not cc.should_speak(kind, now):
        return {"speaker": "", "text": "", "alias": "", "gated": True}
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
    term = "오빠" if who == "cookie" else "아빠"   # 쿠키는 '오빠', 베르는 '아빠'로 부른다
    prompt = (
        f"지금은 네가 **먼저** {term}에게 톡 말을 거는 상황이야. {term}가 너한테 무슨 말을 한 게 "
        f"아니라({term}는 아직 아무 말도 안 했어), {term} 생각이 나서 네가 문득 말 거는 거야.\n\n"
        f"[계기] {situation}\n\n"
        f"{ctx_block}"
        f"이 상황에 맞춰 {term}에게 짧게 말 걸어 — 한 문장, 길어도 두 문장. 자연스럽고 가볍게, "
        f"부담 주지 말고. {tone} 인사·이름표 없이 그 한마디만. (사용자 호칭은 꼭 '{term}'.)")
    try:
        r = llm.call(alias, prompt, system=system)
        text = (r.get("text") or "").strip()
        if text:
            cc.mark_spoken(kind, now)   # 텀/쿨다운 기준 시각 갱신 (빈 응답엔 안 함)
        return {"speaker": name, "text": text, "alias": alias}
    except Exception as e:
        print(f"[companion] _speak 실패: {e}", flush=True)
        return {"speaker": name, "text": "", "alias": alias}


def say(event: str, place: Optional[str] = None,
        speaker: Optional[str] = None,
        minutes: Optional[int] = None) -> Dict[str, Any]:
    """이벤트에 맞춰 쿠키/베르 중 하나가 거는 한마디. speaker 미지정이면 랜덤.

    반환: {speaker: "쿠키"|"베르", text, alias}. 미설정/실패/게이팅이면 text="".
    """
    # 이벤트별 on/off(어드민)는 여기서, 텀·조용구간은 _speak가. 억제면 _situation도 안 거치게.
    if not cc.event_enabled(event):
        return {"speaker": "", "text": "", "alias": "", "gated": True}
    ctx = _situation(event, place, minutes)
    return _speak(cc.kind_of(event), ctx, speaker)


# ── 차량 출차/주차 — 상태전이는 수집기가, 질문·운행 스레드는 여기서 ──────────
# 수집기(폰)가 BT/GPS로 주차중⇄운전중을 판정하고, 출차/주차 순간에만 아래를 부른다.
# 백엔드는 '어디 가?'를 물은 시각(question_ts)을 운행 스레드(settings['drive'])에 적어두고,
# 주차 때 그 이후 아빠 답(대화)을 찾아 '거기 잘 도착했어?'로 잇는다.

def _first_user_reply_after(after: datetime) -> Optional[str]:
    """출발 질문 이후 아빠가 흐름에 남긴 첫 답(목적지). 없으면 None."""
    try:
        d = db.conversations().find_one(
            {"role": "user", "ts": {"$gt": after}}, sort=[("ts", 1)])
    except Exception:
        return None
    return (d.get("text") or "").strip() if d else None


def car_departure(lat: float, lng: float, ts: Any = None,
                  speaker: Optional[str] = None) -> Dict[str, Any]:
    """출차(주차중→운전중) — '어디 가?' 한마디 + 운행 스레드 시작.

    질문을 실제로 했을 때만 question_ts를 적어, 주차 때 답 매칭의 기준으로 쓴다.
    """
    situation = ("아빠가 방금 차를 몰고 어디론가 출발했어(세워둔 데서 한참 벗어나 움직이기 "
                 "시작). 어디 가는지 궁금해서 가볍게 물어봐 — '어디 가?' 정도로 아주 짧게.")
    r = _speak("car", situation, speaker)
    doc: Dict[str, Any] = {"state": "driving", "departed_at": _ts_to_dt(ts)}
    if (r.get("text") or "").strip():
        doc["question_ts"] = datetime.now()   # '어디 가?'를 실제로 물은 순간
    db.settings().update_one({"_id": "drive"}, {"$set": doc}, upsert=True)
    return r


def car_parking(lat: float, lng: float, ts: Any = None,
                silent: bool = False,
                speaker: Optional[str] = None) -> Dict[str, Any]:
    """주차(운전중→주차중) — 주차 위치(GPS) 기록 + 질문. 운행 스레드 닫음.

    silent=True(안전망: 오래 정지해 조용히 리셋)면 위치만 남기고 말은 안 건다.
    아빠가 출발 때 '어디 가?'에 답했으면 '거기 잘 도착했어?', 아니면 '어디 세웠어?'.
    """
    import parking as parking_mod
    parking_mod.record(lat, lng, ts)            # 위치는 항상 ('내 차 어디?' 회상용)
    drive = db.settings().find_one({"_id": "drive"}) or {}
    db.settings().update_one({"_id": "drive"},
                             {"$set": {"state": "parked", "question_ts": None}},
                             upsert=True)
    if silent:
        return {"speaker": "", "text": "", "alias": ""}
    dest = None
    qts = drive.get("question_ts")
    if isinstance(qts, datetime):
        dest = _first_user_reply_after(qts)
    if dest:
        situation = (f"아빠가 출발할 때 '어디 가?'라고 물으니 '{dest}'라고 했었어. 이제 도착해서 "
                     f"차를 세웠어. 거기('{dest}') 잘 도착했는지 가볍게 안부 물어봐 — 짧게.")
    else:
        situation = ("아빠가 방금 차를 세웠어(도착·주차). 어디 도착했는지·어디 세웠는지 가볍게 "
                     "물어봐 — 짧게, 나중에 차 둔 데 기억하게.")
    return _speak("car", situation, speaker)


# ── 동반자끼리 수다(banter) ─────────────────────────────────────────────
# 아빠가 움직일 때 베르·쿠키가 흐름(conversations)에 자기들끼리 도란도란 주고받는다.
# 도착한 장소의 kind로 '여기 주인'을 정함 — 작업실(office)=베르, 집(home)=쿠키.
_RESIDENT_BY_KIND = {"office": "berr", "home": "cookie"}
_NAME = {"berr": "베르", "cookie": "쿠키"}


def _banter_scene(event: str, info: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """이동/도착 이벤트 → 둘이 나눌 수다의 '장면' 한 줄 + (도착 시) 맞이할 주인 캐릭터."""
    name = info.get("name") if info else None
    if event == "arrive":
        resident = _RESIDENT_BY_KIND.get((info or {}).get("kind") or "")
        where = f"'{name}'" if name else "어딘가"
        scene = f"아빠가 방금 {where}에 도착했어."
        desc = ((info or {}).get("description") or "").strip()
        if desc:
            scene += f" (거기: {desc})"
        if resident:
            scene += (f" 거긴 {_NAME[resident]} 네가 있는 곳이야 — 아빠가 너 보러 온 거라, "
                      f"{_NAME[resident]}가 먼저 '우리 보러 왔다!'처럼 반갑게 맞이해.")
        else:
            scene += " 둘이 아빠 왔다고 반갑게 한마디씩 주고받아."
        return scene, resident
    if event == "board":
        return ("아빠가 방금 차에 탔어. 어디 가려나·혹시 우리 보러 오나, "
                "둘이 도란도란 궁금해하며 주고받아."), None
    where = f"'{name}'에서" if name else "어딘가에서"   # leave
    return (f"아빠가 방금 {where} 나서 어디론가 움직이기 시작했어. "
            f"'아빠 어디 가지?' '몰라~' 하고 둘이 궁금해하며 주고받아."), None


def _trigger_text(event: str, info: Optional[Dict[str, Any]]) -> str:
    """이 수다를 일으킨 계기 한 줄 — 흐름에 주석으로(예: '집에 도착했다.')."""
    name = (info or {}).get("name") if info else None
    if event == "arrive":
        return f"{name}에 도착했다." if name else "어딘가에 도착했다."
    if event == "leave":
        return f"{name}에서 나섰다." if name else "어딘가에서 나섰다."
    if event == "board":
        return "차에 탔다."
    return ""


def _parse_banter(text: str) -> List[Tuple[str, str]]:
    """LLM 출력 → [(표시명, 텍스트)]. JSON 배열 우선, 못 읽으면 빈 리스트."""
    import json
    import re
    raw = (text or "").strip()
    arr = None
    try:
        arr = json.loads(raw)
    except Exception:
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            try:
                arr = json.loads(m.group(0))
            except Exception:
                arr = None
    if not isinstance(arr, list):
        return []
    out: List[Tuple[str, str]] = []
    for t in arr:
        if not isinstance(t, dict):
            continue
        who = str(t.get("who") or t.get("speaker") or "").strip().lower()
        name = "쿠키" if who in ("cookie", "쿠키", "c", "kuki") else "베르"
        tx = str(t.get("text") or "").strip()
        if tx:
            out.append((name, tx))
    return out[:4]


def banter(event: str, place: Optional[str] = None,
           minutes: Optional[int] = None) -> Dict[str, Any]:
    """베르·쿠키가 아빠 움직임에 흐름(conversations)에 자기들끼리 주고받는 짧은 수다.

    event: arrive(도착·인사) | leave(나섬·궁금) | board(차 탐·추측).
    각 턴을 흐름에 남기고(companion=True, banter=True), 도착이면 인사 한 줄을 알림용으로 반환.
    반환: {turns:[{speaker,text}], notify:{speaker,text}}. 억제/실패면 turns=[].
    """
    now = datetime.now()
    if not cc.should_speak("banter", now):
        return {"turns": [], "notify": {"speaker": "", "text": ""}, "gated": True}

    info = None
    if place:
        try:
            info = places_mod.lookup(place)
        except Exception:
            info = None
    scene, resident = _banter_scene(event, info)
    if minutes:
        scene += f" (아빠는 거기 약 {minutes}분 있었어)"

    alias = task_alias("quick") or task_alias("insight") or task_alias("chat")
    if not alias:
        return {"turns": [], "notify": {"speaker": "", "text": ""}}
    system = (
        "너희는 둘 다 아빠의 동반자야. 베르(berr)는 강아지 — 다정하고 차분한 편, "
        "쿠키(cookie)는 오목눈이 새 — 발랄하고 장난스러운 편. 지금은 아빠한테 직접 "
        "거는 게 아니라, 너희 둘이 서로 도란도란 짧게 주고받는 대화야.\n"
        "★호칭: **베르는 사용자를 '아빠', 쿠키는 '오빠'**라고 부른다(섞지 마).\n\n"
        f"[베르]\n{personas.current('berr_identity')}\n\n"
        f"[쿠키]\n{personas.current('cookie_identity')}")
    prompt = (
        f"[지금 상황] {scene}\n\n"
        "이 상황에 맞춰 베르와 쿠키가 **서로** 주고받는 짧은 대화를 써. "
        "2~3턴(한 사람당 한두 마디), 각 줄은 아주 짧게 구어체로. 아빠한테 거는 게 "
        "아니라 둘이 얘기하는 거야. 인사·이름표 없이 말만. "
        '결과는 JSON 배열만: [{"who":"berr","text":"..."},{"who":"cookie","text":"..."}]')
    try:
        r = llm.call(alias, prompt, system=system)
        turns = _parse_banter(r.get("text") or "")
    except Exception as e:
        print(f"[companion] banter 실패: {e}", flush=True)
        turns = []
    if not turns:
        return {"turns": [], "notify": {"speaker": "", "text": ""}}

    trigger = _trigger_text(event, info)   # '집에 도착했다.' 같은 흐름 주석(첫 턴에만)
    saved: List[Dict[str, str]] = []
    for i, (name, text) in enumerate(turns):
        when = now + timedelta(seconds=i)   # 순서 보장(같은 초 충돌 방지)
        doc: Dict[str, Any] = {
            "_id": f"bmsg-{when.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "role": "assistant", "text": text, "ts": when, "referenced": [],
            "speaker": name, "companion": True, "banter": True,
        }
        if i == 0 and trigger:
            doc["trigger"] = trigger     # 무엇이 이 수다를 일으켰는지 — 앱이 캡션으로 표시
        db.conversations().insert_one(doc)
        saved.append({"speaker": name, "text": text})
    cc.mark_spoken("banter", now)

    # 도착 알림은 '집·작업실'(거주자 있는 곳)에 왔을 때만 — 아무 정류장마다 '아빠 오셨다'를
    # 띄우지 않게(거주자 없는 새 곳·잠깐 정차는 흐름에만 조용히). 이동/추측(leave·board)도 흐름만.
    notify = (saved[0] if (event == "arrive" and resident and saved)
              else {"speaker": "", "text": ""})
    return {"turns": saved, "notify": notify, "alias": alias}


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
