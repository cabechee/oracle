"""신호 라우터 — 앱 콜렉터의 30분 주기 동기화 (SMS·부재중)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import signals as signals_mod

router = APIRouter()


class SignalsSyncBody(BaseModel):
    sms: List[Dict[str, Any]] = []            # [{from, body, ts(epoch ms)}]
    calls: List[Dict[str, Any]] = []          # [{from, ts(epoch ms)}]
    notifications: List[Dict[str, Any]] = []  # [{app, title, text, ts(epoch ms)}]


@router.post("/signals/sync")
def ep_signals_sync(body: SignalsSyncBody):
    """저장(dedupe) + 새 신호만 로컬 LLM 요약. 새 게 없으면 summary 빈 문자열."""
    try:
        return signals_mod.sync(body.sms, body.calls, body.notifications)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/signals/recent")
def ep_signals_recent(briefs: int = 40, raw: int = 80):
    """신호 로그 화면 — 과거 요약(brief) 타임라인 + 원본 신호 목록(최신순)."""
    try:
        return signals_mod.recent(brief_limit=briefs, signal_limit=raw)
    except Exception as e:
        raise HTTPException(500, str(e))


class FeedbackBody(BaseModel):
    item_index: int
    feedback: Optional[str] = None   # "inaccurate" 또는 None(해제)


@router.post("/signals/brief/{brief_id}/feedback")
def ep_brief_feedback(brief_id: str, body: FeedbackBody):
    """분류 항목 피드백 — "부정확" 표시(추후 재분류 힌트)."""
    ok = signals_mod.set_item_feedback(brief_id, body.item_index, body.feedback)
    if not ok:
        raise HTTPException(404, "brief or item not found")
    return {"ok": True}
