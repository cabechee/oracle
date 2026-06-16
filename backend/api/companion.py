"""위치·시간 이벤트 → 쿠키/베르 한마디 (폰 알림용)."""

from typing import Optional

from fastapi import APIRouter, HTTPException
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


class AskedIn(BaseModel):
    speaker: str = ""               # 베르 | 쿠키 (표시명)
    text: str                       # 동반자가 먼저 건 멘트
    ts: Optional[int] = None        # epoch ms — 아빠가 알림 탭해 들어온 순간


@router.post("/companion/asked")
def ep_companion_asked(body: AskedIn):
    """동반자 선제 멘트를 흐름에 남긴다 — 아빠가 그 멘트에 '기록'으로 답할 때.

    흐름에서 답한 기록 바로 위에, 탭해 들어온 시각으로 얹힌다.
    """
    if not body.text.strip():
        raise HTTPException(400, "text 비어있음")
    from agent import companion
    return companion.record_asked(body.speaker, body.text, body.ts)
