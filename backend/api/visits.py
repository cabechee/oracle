"""방문 라우터 — 체류 종료 시 기록 + '떠남' 멘트, 그날 방문 조회."""

from datetime import date as _date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

import visits as visits_mod

router = APIRouter()


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
