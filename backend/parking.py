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


def record(lat: float, lng: float, ts: Any = None) -> Dict[str, Any]:
    """주차 위치 1건 기록 — 최신이 곧 '내 차 위치'."""
    when = _to_dt(ts)
    doc = {
        "_id": f"park-{when.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "lat": float(lat),
        "lng": float(lng),
        "ts": when,
    }
    db.parking().insert_one(doc)
    return {"id": doc["_id"], "lat": doc["lat"], "lng": doc["lng"],
            "ts": when.isoformat()}


def latest() -> Optional[Dict[str, Any]]:
    """가장 최근 주차 위치 (없으면 None)."""
    d = db.parking().find_one(sort=[("ts", -1)])
    if not d:
        return None
    ts = d.get("ts")
    return {"id": d["_id"], "lat": d.get("lat"), "lng": d.get("lng"),
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts}


def recent(limit: int = 50):
    """최근 주차 기록 (최신순) — 수집 기록 페이지용."""
    out = []
    for d in db.parking().find().sort("ts", -1).limit(limit):
        ts = d.get("ts")
        out.append({"id": d["_id"], "lat": d.get("lat"), "lng": d.get("lng"),
                    "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts})
    return out
