"""장소 방문 — 체류(stay point) 감지로 들어온 방문 기록 + 일기 재료.

폰이 한 곳(누적 평균 좌표 근처)에 일정 시간(~15분) 머물면 '체류'로 보고, 떠나면
그 완결된 방문(시작·종료·장소·체류분)을 여기 저장한다. 정해진 장소(집/작업실)는
place로, 새 장소는 좌표만(추후 학습/라벨). '오늘 다닌 곳'으로 일기에 녹는다.

방문은 '체크포인트'(머문 곳·구간)만 추린 정제 이벤트다 — 그래야 일기 재료가
깔끔하다. 원시 좌표 스트림(동선)은 따로 tracks 컬렉션(tracks.py)에 항상 쌓는다.
여기서 raw를 안 받는 건 프라이버시 때문이 아니라 정확도/정제 목적이다(둘은 별개 저장소).
"""

import hashlib
from datetime import date, datetime, time as dtime
from typing import Any, Dict, List, Optional

import db


def _to_dt(ts: Any) -> datetime:
    """epoch ms(int) | ISO(str) | datetime → datetime."""
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


def record_visit(place: Optional[str], lat: float, lng: float,
                 start_ts: Any, end_ts: Any, minutes: int) -> str:
    """완결된 방문 저장 — start + 좌표 기준 멱등(같은 방문 두 번 안 쌓임)."""
    start = _to_dt(start_ts)
    key = f"{start.strftime('%Y%m%d%H%M')}|{round(float(lat), 4)}|{round(float(lng), 4)}"
    vid = "visit-" + hashlib.sha1(key.encode()).hexdigest()[:12]
    doc = {
        "_id": vid,
        "place": place,                 # 'home' | 'office' | None(새 장소)
        "lat": float(lat),
        "lng": float(lng),
        "start": start,
        "end": _to_dt(end_ts),
        "minutes": int(minutes),
        "label": None,                  # 새 장소 사용자 라벨(추후 학습 단계)
        "created": datetime.now(),
    }
    db.visits().update_one({"_id": vid}, {"$setOnInsert": doc}, upsert=True)
    return vid


def _place_name(v: Dict[str, Any]) -> str:
    p = v.get("place")
    if p == "home":
        return "집"
    if p == "office":
        return "작업실"
    if p:                       # 수집기가 장소 '이름'으로 보냄(차·집·단골카페 등)
        return str(p)
    return v.get("label") or "어떤 곳"


def _live_name(v: Dict[str, Any]) -> Optional[str]:
    """장소명 — 기록값 우선, 없으면 지금 등록된 장소로 GPS 매칭(live). 못 찾으면 None(미지정).

    live 매칭이라, 나중에 그 자리를 장소로 등록하면 옛 방문도 그 이름으로 보인다.
    """
    p = v.get("place")
    if p == "home":
        return "집"
    if p == "office":
        return "작업실"
    if p:
        return str(p)
    if v.get("label"):
        return v["label"]
    try:
        import places
        np = places.nearest(v.get("lat"), v.get("lng"), 150)
        return np.get("name") if np else None
    except Exception:
        return None


def visits_for_day(target: date) -> List[Dict[str, Any]]:
    """그날 방문 목록(시간순) — 일기·타임라인 재료."""
    t0 = datetime.combine(target, dtime.min)
    t1 = datetime.combine(target, dtime.max)
    out: List[Dict[str, Any]] = []
    for v in db.visits().find({"start": {"$gte": t0, "$lte": t1},
                               "error": {"$ne": True}}).sort("start", 1):   # 오류 위치 제외(일기)
        out.append({
            "id": v["_id"],
            "place": v.get("place"),
            "name": _place_name(v),
            "minutes": v.get("minutes", 0),
            "start": v["start"].strftime("%H:%M")
            if isinstance(v.get("start"), datetime) else "",
            "end": v["end"].strftime("%H:%M")
            if isinstance(v.get("end"), datetime) else "",
        })
    return out


def recent(limit: int = 100) -> List[Dict[str, Any]]:
    """최근 방문/여정 구간 (최신순) — 수집 기록 페이지용. 좌표·기간 포함."""
    out: List[Dict[str, Any]] = []
    for v in db.visits().find().sort("start", -1).limit(limit):
        s, e = v.get("start"), v.get("end")
        out.append({
            "id": v["_id"],
            "place": v.get("place"),
            "name": _live_name(v),          # 등록 장소로 live 매칭 — 없으면 None(어드민 '미지정')
            "minutes": v.get("minutes", 0),
            "lat": v.get("lat"), "lng": v.get("lng"),
            "error": bool(v.get("error")),  # 위치 오류 플래그(사용자 표시)
            "start": s.isoformat() if isinstance(s, datetime) else None,
            "end": e.isoformat() if isinstance(e, datetime) else None,
        })
    return out


def day_lines(target: date) -> List[str]:
    """일기 프롬프트용 '오늘 다닌 곳' 문장 리스트."""
    out = []
    for v in visits_for_day(target):
        dur = v["minutes"]
        span = f"{v['start']}~{v['end']}" if v["start"] else ""
        out.append(f"{v['name']} ({span}, 약 {dur}분)")
    return out
