"""원시 동선(track point) — 수집기가 매 틱 보내는 GPS 점을 그대로 보존.

방문(visits.py)이 '머문 곳/구간'만 추린 정제 체크포인트라면, 여기는 **실제 다닌
길 전체**(분당 1점, 운전 중 10초당 1점)를 항상 쌓는다. 여행/일상 분기 없이 늘 저장 —
나중에 역지오코딩으로 동선에 지명 붙이거나 지도로 보여줄 재료. raw를 따로 두는 건
프라이버시가 아니라 정확도/정제 목적(둘은 별개 저장소).
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


def record(lat: float, lng: float, ts: Any = None,
           acc: Optional[float] = None, source: Optional[str] = None,
           moving: Optional[bool] = None) -> str:
    """동선 점 1개 저장 — ts+좌표 기준 멱등(같은 틱 두 번 안 쌓임).

    수집기가 틱마다 부른다. acc=정확도(m), moving=도보아님(차/대중교통) 여부.
    """
    t = _to_dt(ts)
    key = f"{t.strftime('%Y%m%d%H%M%S')}|{round(float(lat), 5)}|{round(float(lng), 5)}"
    tid = "trk-" + hashlib.sha1(key.encode()).hexdigest()[:14]
    doc: Dict[str, Any] = {"_id": tid, "ts": t,
                           "lat": float(lat), "lng": float(lng)}
    if acc is not None:
        doc["acc"] = float(acc)
    if source:
        doc["source"] = source
    if moving is not None:
        doc["moving"] = bool(moving)
    db.tracks().replace_one({"_id": tid}, doc, upsert=True)
    return tid


def for_day(target: Optional[date] = None) -> List[Dict[str, Any]]:
    """그날 동선 점(시간순) — 지도·디버그·역지오코딩 재료."""
    target = target or date.today()
    lo = datetime.combine(target, dtime.min)
    hi = datetime.combine(target, dtime.max)
    out: List[Dict[str, Any]] = []
    for d in db.tracks().find({"ts": {"$gte": lo, "$lte": hi}}).sort("ts", 1):
        d["ts"] = d["ts"].isoformat() if isinstance(d["ts"], datetime) else d["ts"]
        out.append(d)
    return out


def recent(limit: int = 200) -> List[Dict[str, Any]]:
    """최근 동선 점(최신순) — 디버그/상태."""
    out: List[Dict[str, Any]] = []
    for d in db.tracks().find().sort("ts", -1).limit(limit):
        d["ts"] = d["ts"].isoformat() if isinstance(d["ts"], datetime) else d["ts"]
        out.append(d)
    return out
