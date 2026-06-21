"""주차 위치 — 차에서 내릴 때 GPS로 자동 지정(좌표·시각). '내 차 어디?' 회상용.

수집기가 차 BT 끊김(하차) 시 /parking으로 보낸다. 동반자가 "어디 세웠는지 기록할까요?"
라고 물어, 아빠가 사진·메모로 디테일을 더하면(기록 탭) 그 record가 주차 상세가 된다.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import db


def _to_dt(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000.0)
        except (ValueError, OSError, OverflowError):
            return datetime.now()
    return datetime.now()


def _place_of(d: Dict[str, Any]) -> Optional[str]:
    """이 주차의 장소명 — 기록 때 잡힌 게 있으면 그것, 없으면 지금 등록된 장소로 매칭(live).

    live 매칭이라, 나중에 그 자리를 '장소'로 등록하면 옛 주차 기록도 그 이름으로 보인다.
    """
    if d.get("place"):
        return d["place"]
    try:
        import places
        # 주차장은 그 장소 등록점에서 수백 m 떨어질 수 있음(집은 WiFi 등록점과 주차 지점이 다름)
        # → 방문/일반(150m)보다 넉넉한 300m로 매칭.
        np = places.nearest(d.get("lat"), d.get("lng"), 300)
        return np.get("name") if np else None
    except Exception:
        return None


def _view(d: Dict[str, Any]) -> Dict[str, Any]:
    ts = d.get("ts")
    return {"id": d["_id"], "lat": d.get("lat"), "lng": d.get("lng"),
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
            "place": _place_of(d), "error": bool(d.get("error"))}


def record(lat: float, lng: float, ts: Any = None,
           place: Optional[str] = None) -> Dict[str, Any]:
    """주차 위치 1건 기록 — 최신이 곧 '내 차 위치'. place=도착지 매칭(집·사무실 등, 있으면)."""
    when = _to_dt(ts)
    doc = {
        "_id": f"park-{when.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "lat": float(lat),
        "lng": float(lng),
        "ts": when,
    }
    if place:
        doc["place"] = place                  # 집·사무실·등록장소면 그 이름 잡아둠
    db.parking().insert_one(doc)
    return _view(doc)


def latest() -> Optional[Dict[str, Any]]:
    """가장 최근 주차 위치 (없으면 None)."""
    d = db.parking().find_one(sort=[("ts", -1)])
    return _view(d) if d else None


def recent(limit: int = 50):
    """최근 주차 기록 (최신순) — 수집 기록 페이지용."""
    return [_view(d) for d in db.parking().find().sort("ts", -1).limit(limit)]
