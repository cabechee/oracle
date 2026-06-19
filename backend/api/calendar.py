"""캘린더 라우터 — 다가오는 일정·오늘 일정·이벤트 생성 + 인증 상태."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import gcal

router = APIRouter()


@router.get("/calendar/status")
def ep_status():
    """인증 상태 — 어드민 캘린더 페이지·앱이 '연동됨?' 판단."""
    return gcal.status()


@router.get("/calendar/upcoming")
def ep_upcoming(days: int = 7):
    """지금부터 days일 일정(시작순). 미인증이면 items=[]·authed=False."""
    return {"items": gcal.upcoming(days=days), "authed": gcal.is_authed()}


@router.get("/calendar/today")
def ep_today():
    """오늘 일정 + 한 줄 표현(동반자·일기 배경 재료)."""
    return {"items": gcal.today_events(), "lines": gcal.day_lines()}


class EventIn(BaseModel):
    title: str
    start: str                       # ISO8601(시각) 또는 YYYY-MM-DD(종일)
    end: Optional[str] = None
    description: str = ""
    location: str = ""
    all_day: bool = False


@router.post("/calendar/events")
def ep_create(body: EventIn):
    """이벤트 생성 — 기록/리마인더를 일정으로 올릴 때. 미인증이면 503."""
    if not body.title.strip() or not body.start.strip():
        raise HTTPException(400, "title·start 필요")
    ev = gcal.create_event(body.title, body.start, body.end,
                           body.description, body.location, body.all_day)
    if ev is None:
        raise HTTPException(503, "캘린더 미인증 또는 생성 실패")
    return ev
