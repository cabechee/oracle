"""대화 모드 라우터 — 히스토리 탭 채팅."""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent import chat as chat_mod

router = APIRouter()


class ChatReq(BaseModel):
    message: str
    mention_ids: List[str] = []   # 아빠가 콕 집어 언급한 과거 record id


@router.post("/chat")
def ep_chat(body: ChatReq):
    """대화 한 턴 → user/assistant 메시지 쌍 반환 (둘 다 저장됨)."""
    if not body.message.strip():
        raise HTTPException(400, "message 비어있음")
    try:
        return chat_mod.chat(body.message.strip(), mention_ids=body.mention_ids)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/chat/history")
def ep_chat_history(limit: int = 200):
    """최근 대화 메시지(최신순) — 앱이 record 타임라인과 merge."""
    return {"items": chat_mod.history(limit)}


@router.post("/chat/action/{message_id}/confirm")
def ep_action_confirm(message_id: str):
    """제안된 액션 확인 → 실행(캘린더 일정 등록). 미인증/실패면 ok=False·reason."""
    return chat_mod.confirm_action(message_id)


@router.post("/chat/action/{message_id}/cancel")
def ep_action_cancel(message_id: str):
    """제안된 액션 취소(생성 안 함)."""
    return chat_mod.cancel_action(message_id)
