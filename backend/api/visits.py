"""방문 라우터 — 체류 종료 시 기록 + '떠남' 멘트, 그날 방문 조회."""

from datetime import date as _date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

import visits as visits_mod

router = APIRouter()


class VisitEnd(BaseModel):
    place: Optional[str] = None    # 'home' | 'office' | None(새 장소)
    lat: float
    lng: float
    start_ts: Any                  # epoch ms 또는 ISO
    end_ts: Any
    minutes: int
    speaker: Optional[str] = None


@router.post("/visits")
def ep_visit_end(body: VisitEnd):
    """완결된 방문 기록 + 쿠키/베르 '한동안 있다 가네' 한마디."""
    visits_mod.record_visit(body.place, body.lat, body.lng,
                            body.start_ts, body.end_ts, body.minutes)
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
