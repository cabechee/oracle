"""동반자 말 걸기 정책 — 어드민(/admin)에서 조정하는 스케줄·조건 + 게이팅.

agent.companion.say()가 메시지를 만들기 **전에** 여기에 물어본다(지금 말 걸어도 되나?).
FCM 없이 폰이 자주 호출(정기는 30분 신호동기화 편승, 위치는 1분 폴링)하므로,
'텀·조용 구간·이벤트 on/off' 판단은 서버에서 한 곳으로 모은다. 게이팅이 LLM 호출보다
앞서므로 억제될 땐 비용이 들지 않는다.

- 설정: settings['companion']  (어드민 편집, DEFAULTS 위에 override)
- 상태: settings['companion_state']  (마지막 발화 시각 — 텀/쿨다운 판정)
"""

from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional

import db

# 위치 말 걸기 — 장소 타입(집/작업실)으로 쪼개지 않고 '저장된 장소' 단위로.
# (LLM이 장소 이름·설명을 보고 알아서 말하므로 도착/나섬 둘이면 충분.)
LOCATION_EVENTS = ("arrive_place", "park")

# 어드민 표시 라벨 (UI 폼 구성용)
EVENT_LABELS = {
    "arrive_place": "장소 도착",
    "park": "주차 — 차에서 내림(어디 세웠는지 기록 물어봄)",
}

# 이벤트명 → 표준. 레거시(arrive_home 등)·미사용(leave_*, 떠남은 silent 기록)도 매핑.
_EVENT_CANON = {
    "arrive_place": "arrive_place", "arrive_home": "arrive_place",
    "arrive_office": "arrive_place",
    "park": "park",
    "leave_place": "leave_place", "leave_visit": "leave_place",
    "leave_home": "leave_place", "leave_office": "leave_place",
}

DEFAULTS: Dict[str, Any] = {
    "enabled": True,                # 마스터 — 끄면 일절 안 걺
    # 조용한 새벽 — 정기·위치 모두 침묵 (start~end 시, 자정 넘어가면 wrap)
    "quiet_start_hour": 23,
    "quiet_end_hour": 8,
    # 정기 체크인 ('뭐해?' — 정시(매시 0분)에 1회, 위치와 완전 별개)
    "checkin_enabled": True,
    "checkin_start_hour": 9,        # 활동 시간대 (이 밖엔 정기 안 함)
    "checkin_end_hour": 22,
    # 위치 말 걸기
    "location_enabled": True,
    "location_cooldown_min": 30,    # 위치 메시지 최소 간격
    "location_events": {e: True for e in LOCATION_EVENTS},
    # 동반자끼리 수다(흐름에 도란도란) — 이동/도착 때 베르·쿠키가 주고받는 짧은 대화
    "banter_cooldown_min": 5,       # 플래핑 방지용 최소 간격(이동 이벤트는 보통 더 띄엄띄엄)
}

_HOUR_KEYS = ("quiet_start_hour", "quiet_end_hour",
              "checkin_start_hour", "checkin_end_hour")
_MIN_KEYS = ("location_cooldown_min", "banter_cooldown_min")
_BOOL_KEYS = ("enabled", "checkin_enabled", "location_enabled")


def get_config() -> Dict[str, Any]:
    """DEFAULTS 위에 어드민 override를 얹은 현재 설정 (location_events는 깊은 병합)."""
    doc = db.settings().find_one({"_id": "companion"}) or {}
    cfg = dict(DEFAULTS)
    cfg["location_events"] = dict(DEFAULTS["location_events"])
    for k, v in doc.items():
        if k == "_id":
            continue
        if k == "location_events" and isinstance(v, dict):
            for ek, ev in v.items():
                if ek in DEFAULTS["location_events"]:
                    cfg["location_events"][ek] = bool(ev)
        elif k in DEFAULTS:
            cfg[k] = v
    return cfg


def set_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """어드민 저장 — 알려진 키만 정규화해 반영. 반환=병합된 설정."""
    cur = db.settings().find_one({"_id": "companion"}) or {}
    out: Dict[str, Any] = {k: v for k, v in cur.items() if k != "_id"}
    for k, v in (patch or {}).items():
        if k in _BOOL_KEYS:
            out[k] = bool(v)
        elif k in _HOUR_KEYS:
            try:
                out[k] = max(0, min(23, int(v)))
            except (TypeError, ValueError):
                continue
        elif k in _MIN_KEYS:
            try:
                out[k] = max(1, min(1440, int(v)))
            except (TypeError, ValueError):
                continue
        elif k == "location_events" and isinstance(v, dict):
            ev = dict(out.get("location_events") or {})
            for ek, eb in v.items():
                if ek in DEFAULTS["location_events"]:
                    ev[ek] = bool(eb)
            out["location_events"] = ev
    db.settings().update_one({"_id": "companion"}, {"$set": out}, upsert=True)
    return get_config()


def kind_of(event: str) -> str:
    """이벤트 → 게이팅 종류. 주차는 'park'(항상), 위치는 'location', 그 외는 'checkin'(정기)."""
    if event == "park":
        return "park"
    return "location" if event in _EVENT_CANON else "checkin"


def _in_window(hour: int, start: int, end: int) -> bool:
    """[start, end) 시 윈도우 포함 여부. start==end면 빈 구간. wrap(밤샘, 예 23~8) 지원."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _minutes_since(last: Any, now: datetime) -> float:
    if not isinstance(last, datetime):
        return 1e9   # 기록 없음 → 충분히 오래전으로
    return (now - last).total_seconds() / 60.0


def _state() -> Dict[str, Any]:
    return db.settings().find_one({"_id": "companion_state"}) or {}


def event_enabled(event: str, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """이벤트별 on/off. 레거시 이름(arrive_home 등)은 표준(arrive_place/leave_place)으로 매핑."""
    canon = _EVENT_CANON.get(event)
    if canon is None:
        return True   # checkin 등 — 위치 이벤트 아님
    cfg = cfg or get_config()
    return bool(cfg.get("location_events", {}).get(canon, True))


def should_speak(kind: str, now: Optional[datetime] = None,
                 cfg: Optional[Dict[str, Any]] = None) -> bool:
    """지금 그 종류로 말 걸어도 되나 — 마스터·조용구간·활동시간대·텀/쿨다운 종합."""
    now = now or datetime.now()
    cfg = cfg or get_config()
    if not cfg.get("enabled", True):
        return False
    # 새벽 조용 구간 — 정기·위치 모두 침묵
    if _in_window(now.hour, int(cfg["quiet_start_hour"]), int(cfg["quiet_end_hour"])):
        return False
    st = _state()
    if kind == "checkin":
        if not cfg.get("checkin_enabled", True):
            return False
        if not _in_window(now.hour, int(cfg["checkin_start_hour"]),
                          int(cfg["checkin_end_hour"])):
            return False
        if now.minute >= 5:   # 정각(매시 0~4분)에만 — 중간 시작 시 catch-up 방지
            return False
        # 정시 1회 — 이 시(연-월-일-시)에 아직 안 보냈으면 OK. 위치와 완전 별개.
        last = st.get("last_checkin")
        if isinstance(last, datetime) and (
                (last.year, last.month, last.day, last.hour)
                == (now.year, now.month, now.day, now.hour)):
            return False
        return True
    if kind == "park":
        # 주차는 매번(조용 구간만 피함) — BT 플래핑 방지용 짧은 자체 쿨다운만.
        return _minutes_since(st.get("last_park"), now) >= 2
    if kind == "banter":
        # 동반자끼리 수다 — 위치 켜져 있을 때만, 플래핑 방지 짧은 쿨다운(위치 쿨다운과 별개).
        if not cfg.get("location_enabled", True):
            return False
        return _minutes_since(st.get("last_banter"), now) >= int(
            cfg.get("banter_cooldown_min", 5))
    # location
    if not cfg.get("location_enabled", True):
        return False
    return _minutes_since(st.get("last_location"), now) >= int(
        cfg["location_cooldown_min"])


def mark_spoken(kind: str, now: Optional[datetime] = None) -> None:
    """실제로 말 건 직후 호출 — 텀/쿨다운 기준 시각 갱신."""
    now = now or datetime.now()
    if kind == "park":
        # 주차 — last_park + last_location 둘 다 갱신(직후 '도착' 메시지 억제 = 디클러스터).
        db.settings().update_one(
            {"_id": "companion_state"},
            {"$set": {"last_park": now, "last_location": now}}, upsert=True)
        return
    if kind == "banter":
        db.settings().update_one({"_id": "companion_state"},
                                 {"$set": {"last_banter": now}}, upsert=True)
        return
    field = "last_checkin" if kind == "checkin" else "last_location"
    db.settings().update_one({"_id": "companion_state"},
                             {"$set": {field: now}}, upsert=True)


def _period(hour: int) -> str:
    if 6 <= hour < 11:
        return "아침"
    if 11 <= hour < 14:
        return "점심때"
    if 14 <= hour < 18:
        return "오후"
    if 18 <= hour < 22:
        return "저녁"
    return "밤"


def gather_context(now: Optional[datetime] = None) -> str:
    """말 걸 때 곁들일 실제 맥락 — 시간대 + 쌓인 신호 + 오늘 기록/방문.

    LLM이 이 중 자연스러운 것만 슬쩍 녹이게 한다(다 나열 X). 각 소스는 graceful.
    """
    now = now or datetime.now()
    bits = [f"지금 {now.strftime('%H시 %M분')} ({_period(now.hour)})"]
    try:
        import signals as signals_mod
        dg = signals_mod.today_digest()
        sc = int(dg.get("signal_count") or 0)
        if sc:
            attn = int((dg.get("totals") or {}).get("attention") or 0)
            extra = f" (관심 {attn}건)" if attn else ""
            bits.append(f"오늘 받은 알림(문자·부재중·앱) {sc}건 쌓여 있음{extra}")
    except Exception:
        pass
    try:
        t0 = datetime.combine(now.date(), dtime.min)
        n = db.records().count_documents(
            {"ts": {"$gte": t0, "$lte": now}, "hidden": {"$ne": True}})
        bits.append(f"오늘 아빠가 남긴 기록 {n}건")
    except Exception:
        pass
    try:
        import visits as visits_mod
        lines = visits_mod.day_lines(now.date())
        if lines:
            bits.append("오늘 다닌 곳: " + "; ".join(lines[:4]))
    except Exception:
        pass
    return "\n".join(f"- {b}" for b in bits)


def state_view() -> Dict[str, Any]:
    """어드민 표시용 — 마지막 발화가 언제였는지(분 전)."""
    now = datetime.now()
    st = _state()
    def ago(last: Any) -> Optional[int]:
        m = _minutes_since(last, now)
        return None if m >= 1e8 else int(m)
    return {
        "checkin_ago_min": ago(st.get("last_checkin")),
        "location_ago_min": ago(st.get("last_location")),
    }
