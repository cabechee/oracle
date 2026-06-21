"""발행물 라우터 — 조간·석간 합성(cron) + 조회(앱)."""

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException

import briefing as briefing_mod

router = APIRouter()


@router.post("/briefing/run")
def ep_run(kind: str, target_date: Optional[str] = None):
    """조간/석간 합성 — cron(오늘) 또는 앱 '재처리'(target_date=YYYY-MM-DD로 과거 재생성)."""
    target = None
    if target_date:
        try:
            target = _date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(400, "target_date must be YYYY-MM-DD")
    if kind == "morning":
        return briefing_mod.run_morning(target)
    if kind == "evening":
        return briefing_mod.run_evening(target)
    raise HTTPException(400, "kind must be morning or evening")


@router.get("/briefing/latest")
def ep_latest(kind: Optional[str] = None):
    """최신 발행물 (kind 지정 가능). 홈 표지·알림 폴링용."""
    return briefing_mod.latest(kind) or {}


@router.get("/briefing/list")
def ep_list(limit: int = 30):
    return {"items": briefing_mod.recent(limit)}
