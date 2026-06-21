"""방문 라우터 — 체류 종료 시 기록 + '떠남' 멘트, 그날 방문 조회."""

from datetime import date as _date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

import visits as visits_mod

router = APIRouter()


@router.get("/collector-records")
def ep_collector_records(limit: int = 100):
    """수집기가 저장한 기록 전체 — 여정(방문)·주차·신호(최신순). 어드민 '수집 기록' 페이지."""
    import parking as parking_mod
    import signals as signals_mod
    try:
        signals = signals_mod.recent(brief_limit=1, signal_limit=limit).get("signals", [])
    except Exception:
        signals = []
    return {
        "visits": visits_mod.recent(limit),
        "parking": parking_mod.recent(60),
        "signals": signals,
    }


class VisitEnd(BaseModel):
    place: Optional[str] = None    # 'home' | 'office' | 장소 이름 | None(새 장소)
    lat: float
    lng: float
    start_ts: Any                  # epoch ms 또는 ISO
    end_ts: Any
    minutes: int
    speaker: Optional[str] = None
    silent: bool = False           # 여정 기록 전용(말 걸기 생략) — 수집기 단독화 후 기본 흐름


@router.post("/visits")
def ep_visit_end(body: VisitEnd):
    """완결된 방문 기록 + (silent 아니면) 쿠키/베르 '한동안 있다 가네' 한마디.

    수집기는 여정(집→차→사무실→…)을 silent로 기록하고, 말 걸기는 도착 시 별도로 한다.
    """
    visits_mod.record_visit(body.place, body.lat, body.lng,
                            body.start_ts, body.end_ts, body.minutes)
    if body.silent:
        return {"ok": True, "text": ""}
    from agent import companion
    msg = companion.say("leave_visit", place=body.place,
                        speaker=body.speaker, minutes=body.minutes)
    return {"ok": True, **msg}


@router.get("/visits")
def ep_visits(date: Optional[str] = None):
    """그날(기본 오늘) 방문 목록 — 타임라인·디버그."""
    try:
        target = _date.fromisoformat(date) if date else _date.today()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return {"items": visits_mod.visits_for_day(target)}


class ParkIn(BaseModel):
    lat: float
    lng: float
    ts: Any = None                 # epoch ms 또는 ISO
    speaker: Optional[str] = None


@router.post("/parking")
def ep_parking(body: ParkIn):
    """차에서 내림 — 주차 위치(GPS) 지정 기록 + '어디 세웠는지 기록할까요?' 말 걸기.

    기록은 항상(위치 지정), 말 걸기는 동반자 게이팅(조용 구간·텀)에 따름.
    """
    import parking as parking_mod
    parking_mod.record(body.lat, body.lng, body.ts)
    from agent import companion
    msg = companion.say("park", speaker=body.speaker)
    return {"ok": True, **msg}


@router.get("/parking/latest")
def ep_parking_latest():
    """가장 최근 주차 위치 — '내 차 어디?' 회상용."""
    import parking as parking_mod
    return {"parking": parking_mod.latest()}


class LabelIn(BaseModel):
    kind: str                      # "visit" | "parking"
    id: str
    name: str
    lat: Optional[float] = None
    lng: Optional[float] = None


@router.post("/locations/label")
def ep_label(body: LabelIn):
    """수집기록의 한 위치에 라벨 — 그 기록을 이 이름으로 보이게 + 그 자리를 '장소'로 등록.

    같은 이름 장소가 이미 있으면 **수정**(중복 안 만듦, GPS는 기존 유지). 없으면 그 좌표로 새로.
    """
    import db
    import places as places_mod
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name 비어있음")
    if body.kind == "visit":
        db.visits().update_one({"_id": body.id}, {"$set": {"label": name}})
    elif body.kind == "parking":
        db.parking().update_one({"_id": body.id}, {"$set": {"place": name}})
    else:
        raise HTTPException(400, "kind는 visit|parking")
    existing = places_mod.lookup(name)            # 이름으로 dedup
    if existing:
        place = places_mod.upsert(name=name, place_id=existing["id"],
                                  lat=existing.get("lat") or body.lat,
                                  lng=existing.get("lng") or body.lng)
    else:
        place = places_mod.upsert(name=name, kind="place", lat=body.lat, lng=body.lng)
    return {"ok": True, "place": place, "updated": bool(existing)}


def _loc_coll(kind: str):
    import db
    if kind == "visit":
        return db.visits()
    if kind == "parking":
        return db.parking()
    raise HTTPException(400, "kind는 visit|parking")


class EditLocIn(BaseModel):
    kind: str
    id: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    error: Optional[bool] = None    # 위치 오류 플래그(켜면 일기·동반자 맥락서 제외)


@router.post("/locations/edit")
def ep_edit_location(body: EditLocIn):
    """수집기록 위치 보정 — 좌표 직접 수정 / 오류 플래그(잘못 찍힌 위치)."""
    coll = _loc_coll(body.kind)
    upd: dict = {}
    if body.lat is not None:
        upd["lat"] = body.lat
    if body.lng is not None:
        upd["lng"] = body.lng
    if body.error is not None:
        upd["error"] = bool(body.error)
    if not upd:
        raise HTTPException(400, "수정할 내용 없음(lat/lng/error)")
    coll.update_one({"_id": body.id}, {"$set": upd})
    return {"ok": True, "updated": upd}


class DelLocIn(BaseModel):
    kind: str
    id: str


@router.post("/locations/delete")
def ep_delete_location(body: DelLocIn):
    """수집기록 위치 삭제(오기록 정리)."""
    n = _loc_coll(body.kind).delete_one({"_id": body.id}).deleted_count
    return {"ok": n > 0}
