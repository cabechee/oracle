"""위치·시간 이벤트 → 쿠키/베르 한마디 (폰 알림용)."""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class SayIn(BaseModel):
    event: str                      # arrive_home | arrive_office | leave_* | deviate | checkin
    place: Optional[str] = None     # 장소명(선택) — 프롬프트 맥락
    speaker: Optional[str] = None   # cookie | berr (미지정=랜덤)


@router.post("/companion/say")
def ep_companion_say(body: SayIn):
    from agent import companion
    return companion.say(body.event, body.place, body.speaker)
