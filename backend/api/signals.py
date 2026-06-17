"""신호 라우터 — 수집기(앱·네이티브)의 주기 동기화 (SMS·부재중·알림) + 수집기 설정."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

import signals as signals_mod
import collector_config as coll_cfg

router = APIRouter()


class SignalsSyncBody(BaseModel):
    sms: List[Dict[str, Any]] = []            # [{from, body, ts(epoch ms)}]
    calls: List[Dict[str, Any]] = []          # [{from, ts(epoch ms)}]
    notifications: List[Dict[str, Any]] = []  # [{app, title, text, ts(epoch ms)}]
    source: Optional[str] = None              # 보낸 클라이언트/기기 (provenance) — 수집기 vs 폰


@router.post("/signals/sync")
def ep_signals_sync(body: SignalsSyncBody):
    """저장(dedupe) + 새 신호만 로컬 LLM 요약. 새 게 없으면 summary 빈 문자열."""
    try:
        return signals_mod.sync(body.sms, body.calls, body.notifications,
                                source=body.source)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── 수집기 설정 (어드민 조정 → 수집기가 fetch해 적용) ──────────────
@router.get("/collector-config")
def ep_get_collector_config():
    return {"config": coll_cfg.get_config()}


@router.post("/collector-config")
def ep_set_collector_config(patch: Dict[str, Any] = Body(...)):
    """수집기 설정 부분 갱신 (sync_interval_min·수집 항목 on/off·enabled)."""
    return {"config": coll_cfg.set_config(patch)}


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
