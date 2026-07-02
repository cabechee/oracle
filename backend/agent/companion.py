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


def _area_of(lat: Any, lng: Any) -> Optional[str]:
    """좌표 → 지역명(Kakao 역지오코딩, geocache). '어디야?' 대신 '○○동 쪽이네' 할 재료.

    키 없으면 DB도 안 건드리고 None — 미설정 환경에서 기존 발화 그대로.
    """
    try:
        from config import KAKAO_REST_KEY
        if not KAKAO_REST_KEY:
            return None
        import geocode
        return geocode.reverse(lat, lng)
    except Exception:
        return None


def _pending_area(now: Optional[datetime] = None) -> Optional[str]:
    """askplace 직전 저장된 pending_place 좌표 → 지역명. 10분 넘게 묵으면 남의 방문 것 — 무시."""
    now = now or datetime.now()
    try:
        from config import KAKAO_REST_KEY
        if not KAKAO_REST_KEY:
            return None
        pp = db.settings().find_one({"_id": "pending_place"}) or {}
        ts = pp.get("ts")
        if not isinstance(ts, datetime) or (now - ts) > timedelta(minutes=10):
            return None
        return _area_of(pp.get("lat"), pp.get("lng"))
    except Exception:
        return None


def _recent_visit_area(now: Optional[datetime] = None) -> Optional[str]:
    """방금 끝난 미등록 방문의 좌표 → 지역명 — banter leave가 '어딘가' 대신 지명을 알게.

    수집기는 이탈 확정 때 방문 구간을 먼저 기록하고 banter를 부른다(순서 보장) — 그 방금 것.
    """
    now = now or datetime.now()
    try:
        from config import KAKAO_REST_KEY
        if not KAKAO_REST_KEY:
            return None
        v = db.visits().find_one(
            {"$or": [{"place": None}, {"place": ""}],
             "end": {"$gte": now - timedelta(minutes=20)}},
            sort=[("end", -1)])
        if not v:
            return None
        return _area_of(v.get("lat"), v.get("lng"))
    except Exception:
        return None


def _recent_speech(hours: int = 36, limit: int = 5) -> str:
    """최근 동반자 발화(선제·수다) 몇 줄 — '또 어디 가요?' 같은 재탕 방지용 프롬프트 재료."""
    since = datetime.now() - timedelta(hours=hours)
    try:
        cur = (db.conversations()
               .find({"companion": True, "ts": {"$gte": since}})
               .sort("ts", -1).limit(limit))
        lines = []
        for d in cur:
            ts = d.get("ts")
            hm = ts.strftime("%m-%d %H:%M") if hasattr(ts, "strftime") else ""
            txt = (d.get("text") or "").replace("\n", " ").strip()[:70]
            if txt:
                lines.append(f"- ({hm} {d.get('speaker', '')}) {txt}")
        return "\n".join(reversed(lines))   # 시간순
    except Exception:
        return ""


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
        s = "아빠가 저장 안 된 새로운 곳에 와서 15분 넘게 머무는 중이야. "
        area = _pending_area()
        if area:
            s += f"위치로 보면 '{area}' 근처라는 것까진 아는데, 뭐 하는 곳인지는 몰라. "
        s += ("여기가 어디인지·뭐 하는 곳인지 가볍게 물어봐 — '아빠 왔다'처럼 반기지 말고"
              "(여긴 우리 집이 아니야), 자주 오는 곳이면 기억해둘 수 있게 호기심으로. "
              "답해주면 그 장소를 저장해둘게.")
    elif event == "checkin":
        s = "지금 아빠가 뭐 하고 있을까, 문득 궁금해졌어."
    else:
        s = "아빠한테 가볍게 말 걸고 싶어."
    if minutes:
        s += f" (그곳에 약 {minutes}분 있었어)"
    return s


def _speak(kind: str, situation: str, speaker: Optional[str] = None,
           comment: str = "", force: bool = False) -> Dict[str, Any]:
    """게이팅 통과 시 쿠키/베르 중 하나가 situation에 맞춰 거는 한마디(아빠한테 직접).

    say()·car_departure()·car_parking()의 공통 코어 — 페르소나/말투/맥락/LLM 호출.
    comment=재처리 피드백, force=게이팅·텀 무시(재처리 시 True).
    반환: {speaker, text, alias}. 미설정/실패/게이팅이면 text="".
    """
    now = datetime.now()
    # 지금 말 걸 타이밍인가 — 마스터·새벽 조용구간·텀/쿨다운. (LLM 전에 막아 억제 시 비용 0)
    if not force and not cc.should_speak(kind, now):
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
    recent = _recent_speech()   # 최근에 이미 건 말들 — 같은 표현 재탕 방지
    term = "오빠" if who == "cookie" else "아빠"   # 쿠키는 '오빠', 베르는 '아빠'로 부른다
    # 계기·맥락 텍스트는 '아빠'로 서술돼 있음 — 쿠키면 호칭 일관 치환(안 하면 '오빠, 아빠…' 섞임).
    if term != "아빠":
        situation = situation.replace("아빠", term)
        real_ctx = real_ctx.replace("아빠", term)
        recent = recent.replace("아빠", term)
    ctx_block = (
        f"[요즘 상황 — 이 중 자연스러운 게 있으면 하나만 슬쩍 녹여도 좋아. 다 나열하지 말고, "
        f"억지로 엮지 말고, 없으면 그냥 가볍게. **단, 오늘 기록에 이미 한 일(예: 점심을 이미 "
        f"먹었으면)은 또 하라고 권하지 마 — 이미 한 걸 아니까.**]\n{real_ctx}\n\n" if real_ctx else "")
    recent_block = (
        f"[최근에 이미 건 말들 — 표현·패턴이 되풀이되지 않게, 이번엔 다른 결로]\n"
        f"{recent}\n\n" if recent else "")
    prompt = (
        f"지금은 네가 **먼저** {term}에게 톡 말을 거는 상황이야. {term}가 너한테 무슨 말을 한 게 "
        f"아니라({term}는 아직 아무 말도 안 했어), {term} 생각이 나서 네가 문득 말 거는 거야.\n\n"
        f"[계기] {situation}\n\n"
        f"{ctx_block}"
        f"{recent_block}"
        f"이 상황에 맞춰 {term}에게 짧게 말 걸어 — 한 문장, 길어도 두 문장. 자연스럽고 가볍게, "
        f"부담 주지 말고. {tone} 인사·이름표 없이 그 한마디만. (사용자 호칭은 꼭 '{term}'.) "
        f"네가 아는 건 계기·상황에 적힌 것뿐이야 — 본 것처럼 소리·옷차림·행동을 지어내지 마.")
    prompt += personas.feedback_block(comment)   # 재처리면 사용자 지적 반영
    try:
        r = llm.call_retry(alias, prompt, tries=2, system=system)   # 529류 일시 오류에 발화 유실 방지
        text = (r.get("text") or "").strip()
        if text and not force:
            cc.mark_spoken(kind, now)   # 텀/쿨다운 기준 시각 갱신 (재처리·빈 응답엔 안 함)
        return {"speaker": name, "text": text, "alias": alias}
    except Exception as e:
        print(f"[companion] _speak 실패: {e}", flush=True)
        return {"speaker": name, "text": "", "alias": alias}


def _say_trigger(event: str, place: Optional[str]) -> str:
    """say 발화의 흐름 캡션 — 무엇이 말을 걸게 했나(앱이 발화 위에 표시)."""
    if event == "askplace":
        return "새로운 곳"
    if event == "park":
        return "주차"
    if event in _ARRIVE:
        return f"{place} 도착" if place else "도착"
    if event in _LEAVE:
        return f"{place}에서 나섬" if place else "이동"
    return ""


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
    kind = cc.kind_of(event)
    r = _speak(kind, ctx, speaker)
    # 위치 발화(askplace·도착/나섬·주차)는 차 멘트처럼 흐름에도 자동 저장 — 알림을 놓쳐도
    # 남고, 재처리(regen)도 가능. checkin은 잦아서 알림만(흐름 도배 방지).
    if kind in ("location", "park") and (r.get("text") or "").strip():
        _log_companion(r.get("speaker"), r.get("text"),
                       trigger=_say_trigger(event, place),
                       regen={"kind": kind, "situation": ctx,
                              "speaker": _speaker_code(r.get("speaker"))})
    return r


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


def _tesla_budget_ok() -> bool:
    """테슬라 호출 일일 상한(비용 가드). 오늘 카운트<cap이면 +1 후 True, 초과면 False."""
    import config as _cfg
    cap = int(getattr(_cfg, "TESLA_DAILY_CAP", 50))
    today = datetime.now().strftime("%Y-%m-%d")
    st = db.settings().find_one({"_id": "tesla_usage"}) or {}
    if st.get("date") != today:
        db.settings().update_one({"_id": "tesla_usage"},
                                 {"$set": {"date": today, "count": 0}}, upsert=True)
        st = {"date": today, "count": 0}
    if int(st.get("count", 0)) >= cap:
        return False
    db.settings().update_one({"_id": "tesla_usage"}, {"$inc": {"count": 1}}, upsert=True)
    return True


def _tesla_at_event() -> Optional[Dict[str, Any]]:
    """이벤트 시점 차 전체 스냅샷(위치·운행·배터리·공조·주행거리계). 미인증·상한초과·자는차·실패면 None.

    location() 호환 필드를 포함하므로 상태머신이 그대로 쓰고, 출차/주차 때 car_snapshots에도 저장된다.
    """
    try:
        import tesla
        if not tesla.is_authed() or not _tesla_budget_ok():
            return None
        # 출차/주차 순간은 차가 깨어 있는 게 확실(BT 연결 판정 직후)인데 차량 목록 state는
        # 캐시가 늦어 asleep으로 나옴 → 사전 체크 생략(진짜 자면 408 → None, 안 깨움).
        return tesla.snapshot(assume_awake=True)
    except Exception as e:
        print(f"[companion] tesla 조회 실패: {e}", flush=True)
        return None


def _save_car_snapshot(snap: Optional[Dict[str, Any]], trigger: str) -> None:
    """차 스냅샷을 car_snapshots에 저장(출차/주차 등 이벤트 시점). 자는 차(None)면 스킵."""
    if not snap:
        return
    now = datetime.now()
    doc = dict(snap)
    doc["_id"] = f"car-{now.strftime('%Y%m%d-%H%M%S')}-{trigger}"
    doc["trigger"] = trigger
    doc["recorded_at"] = now
    try:
        db.car_snapshots().insert_one(doc)
    except Exception as e:
        print(f"[companion] 차 스냅샷 저장 실패: {e}", flush=True)


def _dest_name(tloc: Optional[Dict[str, Any]]) -> Optional[str]:
    """테슬라 목적지 → 등록 장소 이름(집/회사 등) 매칭. 없으면 목적지 문자열, 그도 없으면 None."""
    if not tloc:
        return None
    if tloc.get("dest_lat") is not None and tloc.get("dest_lng") is not None:
        try:
            np = places_mod.nearest(tloc["dest_lat"], tloc["dest_lng"], 200)
            if np and np.get("name"):
                return np["name"]
        except Exception:
            pass
    d = (tloc.get("dest") or "").strip()
    return d or None


def _imminent_event(now: Optional[datetime] = None,
                    ahead_min: int = 120) -> Optional[str]:
    """곧(약 -20분 ~ +ahead_min분) 시작하는 캘린더 일정 → '거기 가?' 추측용 목적지 한 줄.

    출발할 때 네비 목적지가 없으면 일정으로 행선지를 짐작한다. 장소가 있으면 '장소(제목)',
    없으면 제목만. 시각 일정만(종일 제외). 미인증/없음이면 None.
    """
    now = now or datetime.now()
    try:
        import gcal
        evs = gcal.upcoming(days=1, max_results=15)
    except Exception:
        return None
    for e in evs:
        if e.get("all_day"):
            continue
        s = e.get("start") or ""
        try:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            continue
        if t.tzinfo is not None:
            t = t.astimezone().replace(tzinfo=None)
        delta_min = (t - now).total_seconds() / 60.0
        if -20 <= delta_min <= ahead_min:
            title = (e.get("title") or "").strip()
            loc = (e.get("location") or "").strip()
            if loc and title:
                return f"{loc}({title})"
            return loc or title or None
    return None


def _log_companion(speaker: Optional[str], text: str,
                   trigger: Optional[str] = None,
                   when: Optional[datetime] = None,
                   regen: Optional[Dict[str, Any]] = None) -> None:
    """차 출차/주차 멘트를 흐름(conversations)에 자동 저장 — banter처럼 탭 안 해도 흐름에 남게.

    regen={kind,situation,speaker} 저장 시 나중에 코멘트 반영 재처리 가능(reprocess_companion).
    (record_asked가 같은 멘트를 또 저장하지 않게 그쪽에서 최근 동일건은 스킵.)
    """
    text = (text or "").strip()
    if not text:
        return
    when = when or datetime.now()
    doc = {
        "_id": f"cmsg-{when.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "role": "assistant", "text": text, "ts": when, "referenced": [],
        "speaker": (speaker or "").strip(), "companion": True,
    }
    if trigger:
        doc["trigger"] = trigger            # 흐름 캡션(예: '집 도착', '회사로 출발')
    if regen:
        doc["regen"] = regen                # 재처리용 맥락(kind·situation·speaker)
    try:
        db.conversations().insert_one(doc)
    except Exception as e:
        print(f"[companion] 흐름 저장 실패: {e}", flush=True)


def car_departure(lat: float, lng: float, ts: Any = None,
                  speaker: Optional[str] = None, recheck: bool = False) -> Dict[str, Any]:
    """출차(주차중→운전중) — 테슬라로 목적지 확인 후 한마디 + 운행 스레드 시작.

    내비 목적지 있으면 집/회사로 매칭해 '회사 가는구나'(질문 X). 목적지 없으면 **즉답 보류** →
    수집기가 car_dest_recheck_min(기본 3분) 뒤 recheck=True로 다시 부른다 → 그때도 없으면 '어디 가?'.
    (운전 시작 후 내비 찍는 경우를 잡으려고.) 테슬라 미연결/자는차면 graceful.
    단, '어디 가?'에 연속 미답(unanswered_q≥2)이면 캐묻지 않고 가벼운 배웅만 — 질문 피로 방지.
    """
    prev = db.settings().find_one({"_id": "drive"}) or {}
    streak = int(prev.get("unanswered_q") or 0)   # 출발 질문 연속 미답 횟수(주차 때 갱신)
    tloc = _tesla_at_event()
    dest = _dest_name(tloc)
    if not recheck:
        _save_car_snapshot(tloc, "출차")   # 출차 스냅샷(3분 뒤 재확인 호출 땐 중복 저장 X)
    print(f"[car] 출차{'(재확인)' if recheck else ''} — tesla: shift={(tloc or {}).get('shift')} "
          f"dest={dest!r} loc=({(tloc or {}).get('lat')},{(tloc or {}).get('lng')}) "
          f"phone=({lat},{lng})", flush=True)

    if not recheck:
        # 첫 호출 — 운행 시작 기록(출발 시각). 목적지 없으면 즉답 보류하고 수집기 재확인 대기.
        db.settings().update_one(
            {"_id": "drive"},
            {"$set": {"state": "driving", "departed_at": _ts_to_dt(ts), "destination": dest}},
            upsert=True)
        if not dest:
            print("[car] 출차 — 목적지 미설정 → 즉답 보류, 수집기 재확인 대기", flush=True)
            return {"speaker": "", "text": "", "alias": "", "recheck": True}

    asked = False   # 이번 멘트가 '답을 기다리는 질문'인가 — 주차 때 미답 스트릭 판정 기준
    if dest:
        situation = (f"아빠가 차 몰고 '{dest}' 쪽으로 가는 중이야(내비 목적지로 확인됨). 어디 "
                     f"가냐고 묻지 말고 '{dest} 가는구나' 하고 잘 다녀오라 가볍게 인사해 — 짧게.")
    else:   # 재확인에도 목적지 없음 → 일정으로 짐작 → 미답 스트릭 보고 질문/배웅 → '어디 가?'
        ev = _imminent_event()
        if ev:
            situation = (f"아빠가 차를 몰고 어디론가 가는 중이야. 내비 목적지는 안 잡혔는데, 캘린더 "
                         f"보니 곧 '{ev}' 일정이 있어. 혹시 거기 가는 거냐고 가볍게 물어봐 — "
                         f"'{ev} 가?' 정도로 아주 짧게(단정 말고 추측으로).")
            asked = True
        elif streak >= 2:
            # 질문 피로 가드 — 요 며칠 '어디 가?'에 답이 없었으면 또 캐묻지 않는다(답 오면 리셋).
            situation = ("아빠가 차를 몰고 어디론가 나섰어. 요즘 출발할 때 어디 가냐고 물어도 답이 "
                         "잘 없었으니 이번엔 묻지 말고, '조심히 다녀와요' 같은 가벼운 배웅 "
                         "한마디만 — 짧게.")
        else:
            situation = ("아빠가 차를 몰고 어디론가 가는 중이야. 어디 가는지 궁금해서 가볍게 물어봐 "
                         "— '어디 가?' 정도로 아주 짧게.")
            asked = True
    r = _speak("car", situation, "berr")      # 출차(차 탈 때)는 베르 담당
    upd: Dict[str, Any] = {"state": "driving", "asked": False}
    if dest:
        upd["destination"] = dest             # 주차 때 '여기 잘 도착했어?' 매칭 + 목적지 변경 기준
    if (r.get("text") or "").strip():
        if asked:                             # 질문일 때만 — 주차 때 답 매칭·미답 스트릭 기준
            upd["question_ts"] = datetime.now()
            upd["asked"] = True
        _log_companion(r.get("speaker"), r.get("text"),
                       trigger=(f"{dest}로 출발" if dest else "차로 출발"),
                       regen={"kind": "car", "situation": situation, "speaker": "berr"})
    db.settings().update_one({"_id": "drive"}, {"$set": upd}, upsert=True)
    print(f"[car] 출차 멘트({'dest=' + dest if dest else '어디가'}): {(r.get('text') or '')!r}",
          flush=True)
    return r


def car_charging_check(lat: float, lng: float,
                       speaker: Optional[str] = None) -> Dict[str, Any]:
    """운전중 오래 정지(car_charge_check_min) — 테슬라로 충전 중인지 확인.

    충전 중이면 '충전 중이구나' 한마디(+흐름), 아니면 침묵. 어느 쪽이든 상세 로그. 자는 차는 안 깨움.
    """
    try:
        import tesla
        if not tesla.is_authed() or not _tesla_budget_ok():
            print("[car] 충전확인 — 테슬라 미연결/상한 → skip", flush=True)
            return {"speaker": "", "text": "", "charging": None}
        cs = tesla.charge()
    except Exception as e:
        print(f"[car] 충전확인 실패: {e}", flush=True)
        return {"speaker": "", "text": "", "charging": None}
    if not cs:
        print("[car] 충전확인 — 차 오프라인/응답없음(안 깨움)", flush=True)
        return {"speaker": "", "text": "", "charging": None}
    print(f"[car] 충전확인 — state={cs.get('state')!r} charging={cs.get('charging')} "
          f"level={cs.get('level')}% +{cs.get('added_kwh')}kWh", flush=True)
    if not cs.get("charging"):
        return {"speaker": "", "text": "", "charging": False}
    situation = (f"아빠 차가 지금 충전 중이야(배터리 {cs.get('level')}%). 충전 중이라 한자리에 오래 "
                 f"서 있는 거구나 — 가볍게 한마디, 짧게.")
    r = _speak("car", situation, speaker)
    if (r.get("text") or "").strip():
        _log_companion(r.get("speaker"), r.get("text"), trigger="충전 중",
                       regen={"kind": "car", "situation": situation,
                              "speaker": speaker or "berr"})
    return {**r, "charging": True}


def car_parking(lat: float, lng: float, ts: Any = None,
                silent: bool = False,
                speaker: Optional[str] = None) -> Dict[str, Any]:
    """주차(운전중→주차중) — 테슬라로 정밀 위치·도착지 확인 + 질문. 운행 스레드 닫음.

    silent=True(안전망)면 자는 차 깨우기 회피로 테슬라 호출 안 하고 위치만 남기고 침묵.
    도착지가 집/회사면 '집 왔구나', 출발 목적지를 알면 '회사 잘 도착했어?', 아니면 '어디 세웠어?'.
    """
    import parking as parking_mod
    tloc = None if silent else _tesla_at_event()
    _save_car_snapshot(tloc, "주차")   # 주차 스냅샷(silent·자는차면 tloc None → 스킵)
    # 주차 위치 — 테슬라 차 GPS가 있으면 더 정확(폰보다, 특히 실내). 없으면 폰 좌표.
    plat = tloc["lat"] if (tloc and tloc.get("lat") is not None) else lat
    plng = tloc["lng"] if (tloc and tloc.get("lng") is not None) else lng
    here = None                                   # 도착 장소(집/사무실 등) 매칭 — 주차는 넉넉히 300m
    try:
        np = places_mod.nearest(plat, plng, 300)
        here = np.get("name") if np else None
    except Exception:
        here = None
    parking_mod.record(plat, plng, ts, place=here)   # 위치+도착지(집·사무실 등) 항상 기록
    print(f"[car] 주차{'(안전망 silent)' if silent else ''} — tesla shift={(tloc or {}).get('shift')} "
          f"장소={here!r} 기록좌표=({plat},{plng}) phone=({lat},{lng})", flush=True)
    drive = db.settings().find_one({"_id": "drive"}) or {}
    # 출발 질문 미답 스트릭 — 물었는데(asked) 답 없으면 +1, 답 오면 리셋(다음 출발의 배웅 판단).
    qts = drive.get("question_ts")
    asked = bool(drive.get("asked", isinstance(qts, datetime)))   # 구버전 doc은 qts로 판정
    reply = (_first_user_reply_after(qts)
             if (asked and isinstance(qts, datetime)) else None)
    streak = int(drive.get("unanswered_q") or 0)
    if asked and isinstance(qts, datetime):
        streak = 0 if reply else streak + 1
    db.settings().update_one(
        {"_id": "drive"},
        {"$set": {"state": "parked", "question_ts": None, "destination": None,
                  "asked": False, "unanswered_q": streak}},
        upsert=True)
    if silent:
        print("[car] 주차 — 안전망 조용히 리셋(말 X)", flush=True)
        return {"speaker": "", "text": "", "alias": ""}
    dest = drive.get("destination")               # 출발 때 테슬라가 준 목적지
    if not dest:
        dest = reply                              # 아빠가 '어디 가?'에 답한 목적지
    # 운행 시간 힌트 — '잠깐 다녀왔네' vs '오래 걸렸네' 뉘앙스 재료.
    dur_txt = ""
    dep = drive.get("departed_at")
    if isinstance(dep, datetime):
        m = int((datetime.now() - dep).total_seconds() // 60)
        if 1 <= m <= 720:
            dur_txt = f" (약 {m}분 몰았어.)"
    area = None if here else _area_of(plat, plng)   # 미등록 곳 — 지역명으로 아는 척(키 없으면 None)
    unanswered = asked and isinstance(qts, datetime) and not reply
    print(f"[car] 주차 — 도착지매칭 here={here!r} 출발목적지 dest={dest!r} area={area!r} "
          f"미답={unanswered} streak={streak}", flush=True)
    if here:
        situation = (f"아빠가 방금 '{here}'에 도착해서 차를 세웠어.{dur_txt} '{here} 왔구나'처럼 "
                     f"가볍게 맞이해 — 짧게.")
    elif dest:
        situation = (f"아빠가 출발할 때 '{dest}' 간다고 했었어. 이제 도착해서 차를 세웠어.{dur_txt} "
                     f"'{dest} 잘 도착했어?' 하고 가볍게 안부 물어봐 — 짧게.")
    elif unanswered:
        # 출발 때 물었는데 답이 없었다 — 또 캐물으면 보채는 느낌. 아는 척/배려만, 질문 금지.
        if area:
            situation = (f"아빠가 방금 '{area}' 근처에 차를 세웠어.{dur_txt} 출발할 때 어디 가냐고 "
                         f"물었는데 답이 없었으니 또 캐묻진 말고 — '{area} 쪽에 왔구나' 하고 "
                         f"가볍게 아는 척만 해. 차 세운 위치는 네가 기억해뒀다고 살짝 안심시켜도 "
                         f"좋아. 짧게.")
        else:
            situation = (f"아빠가 방금 차를 세웠어(도착·주차).{dur_txt} 출발할 때 어디 가냐고 "
                         f"물었는데 답이 없었으니 또 묻진 말고, 잘 도착했길 바라는 가벼운 "
                         f"한마디만 — 차 세운 위치는 네가 기억해뒀다고 살짝. 짧게.")
    elif area:
        situation = (f"아빠가 방금 '{area}' 근처에 차를 세웠어(저장 안 된 곳).{dur_txt} "
                     f"'{area} 왔구나' 하고 가볍게 아는 척하면서, 뭐 하러 왔는지 딱 한 가지만 "
                     f"살짝 물어봐 — 짧게.")
    else:
        situation = (f"아빠가 방금 차를 세웠어(도착·주차).{dur_txt} 어디 도착했는지 딱 한 가지만 "
                     f"가볍게 물어봐 — 짧게, 나중에 차 둔 데 기억하게.")
    r = _speak("car", situation, "berr")      # 주차(차에서 내릴 때)는 베르 담당
    if (r.get("text") or "").strip():
        _log_companion(r.get("speaker"), r.get("text"),
                       trigger=(f"{here} 도착" if here else "차 세움"),
                       regen={"kind": "car", "situation": situation, "speaker": "berr"})
    print(f"[car] 주차 멘트: {(r.get('text') or '')!r}", flush=True)
    return r


def _speak_dest_change(old_dest: str, new_dest: str) -> Dict[str, Any]:
    """운전 중 내비 목적지 변경 — 쿠키가 가볍게 한마디(중간 변경은 쿠키 전담)."""
    situation = (f"아빠가 운전 중에 내비 목적지를 '{old_dest}'에서 '{new_dest}'로 바꿨어. "
                 f"'어 목적지 바뀌었네? 이제 {new_dest} 가?'처럼 가볍게 한마디 — 짧게.")
    return _speak("dest", situation, "cookie")   # 중간 목적지 변경 = 쿠키


def car_location_poll() -> Dict[str, Any]:
    """운전 중 수집기가 10초마다 호출 — 차 GPS(메인 위치) + 네비 목적지 변경 감지.

    좌표는 폰보다 정확한 차 GPS(자는 차면 None). 운전 중 목적지가 바뀌면 쿠키가 한마디(notify로
    반환 → 수집기가 알림). 출차/주차(탈 때·내릴 때)는 베르, 도중 목적지 변경은 쿠키 담당.
    """
    import tesla
    # 수집기가 '운전 중'이라 판단했을 때만 불림 = 차 깨어 있음 — 목록 state(캐시 지연) 무시.
    loc = tesla.location(assume_awake=True)
    if not loc or loc.get("lat") is None or loc.get("lng") is None:
        return {"lat": None, "lng": None}
    out: Dict[str, Any] = {"lat": loc["lat"], "lng": loc["lng"],
                           "driving": bool(loc.get("driving")), "dest": _dest_name(loc)}
    try:
        drive = db.settings().find_one({"_id": "drive"}) or {}
        if drive.get("state") == "driving":
            new_dest = _dest_name(loc)
            old_dest = drive.get("destination")
            # established 목적지가 바뀐 경우만 = 진짜 중간 변경(첫 목적지는 출차/재확인=베르 담당).
            if old_dest and new_dest and new_dest != old_dest:
                db.settings().update_one({"_id": "drive"},
                                         {"$set": {"destination": new_dest}}, upsert=True)
                r = _speak_dest_change(old_dest, new_dest)
                text = (r.get("text") or "").strip()
                print(f"[car] 목적지 변경 {old_dest!r}→{new_dest!r} 쿠키: {text!r}", flush=True)
                if text:
                    _log_companion(r.get("speaker"), text, trigger=f"목적지 변경 → {new_dest}",
                                   regen={"kind": "dest", "speaker": "cookie",
                                          "situation": f"아빠가 운전 중에 내비 목적지를 '{old_dest}'에서 '{new_dest}'로 바꿨어."})
                    out["notify"] = {"speaker": r.get("speaker"), "text": text}
    except Exception as e:
        print(f"[car] 목적지 변경 감지 실패: {e}", flush=True)
    return out


# ── 동반자끼리 수다(banter) ─────────────────────────────────────────────
# 아빠가 움직일 때 베르·쿠키가 흐름(conversations)에 자기들끼리 도란도란 주고받는다.
# 도착한 장소의 kind로 '여기 주인'을 정함 — 작업실(office)=베르, 집(home)=쿠키.
_RESIDENT_BY_KIND = {"office": "berr", "home": "cookie"}
_NAME = {"berr": "베르", "cookie": "쿠키"}


def _banter_scene(event: str, info: Optional[Dict[str, Any]],
                  moving: Optional[bool] = None,
                  hint: Optional[str] = None,
                  area: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """이동/도착 이벤트 → 둘이 나눌 수다의 '장면' 한 줄 + (도착 시) 맞이할 주인 캐릭터.

    moving=도보아님(차/대중교통) 여부, hint=곧 있는 일정(행선지 추측),
    area=미등록 곳의 역지오코딩 지역명('어딘가' 대신). leave에만 반영.
    """
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
    # leave — 등록 장소면 이름, 아니면 지역명(역지오코딩), 그도 없으면 '어딘가'.
    where = f"'{name}'에서" if name else (f"'{area}' 근처에서" if area else "어딘가에서")
    move_txt = " 차나 대중교통을 타고" if moving else ""
    if hint:
        return (f"아빠가 방금 {where} 나서{move_txt} 어디론가 움직이기 시작했어. "
                f"마침 곧 '{hint}' 일정이 있어 — 혹시 거기 가나 싶어. 둘이 '{hint} 가시나봐?' "
                f"하고 궁금해하며 주고받아."), None
    return (f"아빠가 방금 {where} 나서{move_txt} 어디론가 움직이기 시작했어. "
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


def _recent_arrival(place: Optional[str], now: datetime, within_min: int = 10) -> bool:
    """최근 N분 내 같은 장소 '도착' 발화가 이미 흐름에 있나 — 차 주차('집 도착')와
    WiFi 체류('집에 도착했다')가 같은 도착에 둘 다 인사하는 이중 발화 방지.
    두 트리거 모두 '{장소}…도착'을 포함하므로 그걸로 본다."""
    if not place:
        return False
    import re
    since = now - timedelta(minutes=within_min)
    try:
        doc = db.conversations().find_one({
            "companion": True,
            "ts": {"$gte": since},
            "trigger": {"$regex": re.escape(place) + r".*도착"},
        })
        return doc is not None
    except Exception:
        return False


def banter(event: str, place: Optional[str] = None,
           minutes: Optional[int] = None,
           moving: Optional[bool] = None) -> Dict[str, Any]:
    """베르·쿠키가 아빠 움직임에 흐름(conversations)에 자기들끼리 주고받는 짧은 수다.

    event: arrive(도착·인사) | leave(나섬·궁금) | board(차 탐·추측).
    moving=도보아님(차/대중교통) 여부(leave 장면에 반영).
    각 턴을 흐름에 남기고(companion=True, banter=True), 도착이면 인사 한 줄을 알림용으로 반환.
    나섬(leave) 때 곧 있는 일정이 있으면 '거기 가시나봐?'를 알림으로도 살짝 띄운다.
    반환: {turns:[{speaker,text}], notify:{speaker,text}}. 억제/실패면 turns=[].
    """
    now = datetime.now()
    if not cc.should_speak("banter", now):
        return {"turns": [], "notify": {"speaker": "", "text": ""}, "gated": True}
    # 차로 도착하면 car_parking('집 도착')이 이미 인사함 → 직후 WiFi 체류의 도착 수다는 억제(이중 방지).
    if event == "arrive" and _recent_arrival(place, now):
        print(f"[companion] banter arrive 억제 — 최근 '{place}' 도착 발화 있음", flush=True)
        return {"turns": [], "notify": {"speaker": "", "text": ""}, "gated": True}

    info = None
    if place:
        try:
            info = places_mod.lookup(place)
        except Exception:
            info = None
    leave_hint = _imminent_event() if event == "leave" else None
    # 미등록 곳에서 나섬 — 방금 기록된 방문 좌표를 지역명으로('어딘가' 대신 '○○동 근처').
    area = _recent_visit_area(now) if (event == "leave" and not info) else None
    scene, resident = _banter_scene(event, info, moving, leave_hint, area)
    if minutes:
        scene += f" (아빠는 거기 약 {minutes}분 있었어)"
    scene_for_regen = scene   # 재처리(_speak)는 호칭을 스스로 치환 → '아빠' 유지본 보관
    scene = scene.replace("아빠", "그분")   # 서술의 '아빠'는 중립화 — 쿠키가 베껴 '아빠' 쓰는 것 방지

    alias = task_alias("quick") or task_alias("insight") or task_alias("chat")
    if not alias:
        return {"turns": [], "notify": {"speaker": "", "text": ""}}
    system = (
        "너희는 둘 다 한 사람(그분)의 동반자야. 베르(berr)는 강아지 — 다정하고 차분한 편, "
        "쿠키(cookie)는 오목눈이 새 — 발랄하고 장난스러운 편. 지금은 그분한테 직접 "
        "거는 게 아니라, 너희 둘이 서로 도란도란 짧게 주고받는 대화야.\n"
        "★호칭: 그분을 **베르는 '아빠', 쿠키는 '오빠'**라고 부른다 — 절대 섞지 마"
        "(쿠키 대사에 '아빠'가 나오면 틀린 거야).\n"
        "★너희가 아는 건 [지금 상황]에 적힌 것뿐 — 직접 본 것처럼 옷·신발·소리·행동 같은 "
        "디테일을 지어내지 마.\n\n"
        f"[베르]\n{personas.current('berr_identity')}\n\n"
        f"[쿠키]\n{personas.current('cookie_identity')}")
    recent = _recent_speech()
    recent_block = (
        f"[최근에 너희가 이미 나눈 말들 — 같은 레퍼토리('어디 가시지?', '몰라~')를 "
        f"되풀이하지 말고 이번엔 다른 결로]\n{recent}\n\n" if recent else "")
    prompt = (
        f"[지금 상황] {scene}\n\n"
        f"{recent_block}"
        "이 상황에 맞춰 베르와 쿠키가 **서로** 주고받는 짧은 대화를 써. "
        "2~3턴(한 사람당 한두 마디), 각 줄은 아주 짧게 구어체로. 그분한테 거는 게 "
        "아니라 둘이 얘기하는 거야. **상황 속 '그분'을 베르는 '아빠', 쿠키는 '오빠'로 부른다 — "
        "섞지 마.** 인사·이름표 없이 말만. "
        '결과는 JSON 배열만: [{"who":"berr","text":"..."},{"who":"cookie","text":"..."}]')
    try:
        r = llm.call_retry(alias, prompt, tries=2, system=system)
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
            "regen": {"kind": "banter", "situation": scene_for_regen,
                      "speaker": "cookie" if name == "쿠키" else "berr"},
        }
        if i == 0 and trigger:
            doc["trigger"] = trigger     # 무엇이 이 수다를 일으켰는지 — 앱이 캡션으로 표시
        db.conversations().insert_one(doc)
        saved.append({"speaker": name, "text": text})
    cc.mark_spoken("banter", now)

    # 도착 알림은 '집·작업실'(거주자 있는 곳)에 왔을 때만 — 아무 정류장마다 '아빠 오셨다'를
    # 띄우지 않게(거주자 없는 새 곳·잠깐 정차는 흐름에만 조용히). 이동/추측(leave·board)도 흐름만.
    # 도착(거주자 있는 곳)이거나, 나섬인데 곧 있는 일정으로 행선지가 짐작될 때만 알림으로 띄움.
    # 그 외 평범한 나섬/추측은 흐름에만 조용히(매 이동마다 '어디 가?'로 보채지 않게).
    notify = (saved[0] if ((event == "arrive" and resident) or
                           (event == "leave" and leave_hint)) and saved
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
    txt = (text or "").strip()
    sp = (speaker or "").strip()
    # 차 출차/주차 멘트는 _log_companion이 흐름에 이미 자동 저장 — 탭해 답할 때 중복 방지.
    try:
        dup = db.conversations().find_one({
            "speaker": sp, "text": txt, "companion": True,
            "ts": {"$gte": when - timedelta(minutes=20)}})
    except Exception:
        dup = None
    if dup:
        out = dict(dup)
        dts = out.get("ts")
        out["ts"] = dts.isoformat() if hasattr(dts, "isoformat") else dts
        return out
    doc = {
        "_id": f"cmsg-{when.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "role": "assistant",
        "text": txt,
        "ts": when,
        "referenced": [],
        "speaker": sp,                        # 베르 | 쿠키
        "companion": True,                    # 선제 말걸기 (대화 응답과 구분)
    }
    db.conversations().insert_one(doc)
    out = dict(doc)
    out["ts"] = when.isoformat()
    return out


def _speaker_code(name: Optional[str]) -> str:
    """표시명(베르/쿠키) → 코드(berr/cookie)."""
    return "cookie" if (name or "").strip() == "쿠키" else "berr"


def reprocess_companion(msg_id: str, comment: str = "") -> Optional[Dict[str, Any]]:
    """흐름의 동반자 발화 한 줄을 코멘트 반영해 다시 쓴다(어드민·앱 재처리).

    regen 메타(kind·situation·speaker)가 있으면 그 맥락으로, 없으면(과거 발화)
    trigger·기존 말로 맥락을 근사해 재생성. 게이팅·텀은 무시(force=True).
    """
    doc = db.conversations().find_one({"_id": msg_id, "companion": True})
    if not doc:
        return None
    regen = doc.get("regen") or {}
    kind = regen.get("kind") or "checkin"
    speaker_code = regen.get("speaker") or _speaker_code(doc.get("speaker"))
    situation = regen.get("situation")
    if not situation:
        trig = (doc.get("trigger") or "").strip()
        prev = (doc.get("text") or "").strip()
        situation = (f"'{trig}' 상황에서 네가 흐름에 했던 말을 다시 쓰는 거야."
                     if trig else "네가 흐름에 했던 말을 다시 쓰는 거야.")
        if prev:
            situation += f" (원래 한 말: {prev})"
    r = _speak(kind, situation, speaker_code, comment=comment, force=True)
    text = (r.get("text") or "").strip()
    if not text:
        return {"ok": False, "id": msg_id, "reason": r.get("reason") or "재생성 실패"}
    db.conversations().update_one({"_id": msg_id}, {"$set": {"text": text}})
    ts = doc.get("ts")
    return {"ok": True, "id": msg_id, "speaker": doc.get("speaker"), "text": text,
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts}
