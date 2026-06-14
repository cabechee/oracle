"""가계부 라우터 — 결제 알림에서 모인 지출 조회 + 오기록 삭제."""

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException

import ledger as ledger_mod

router = APIRouter()


@router.get("/ledger")
def ep_today(date: Optional[str] = None):
    """그날(기본 오늘) 가계부 — 총액·건수·항목."""
    try:
        target = _date.fromisoformat(date) if date else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return ledger_mod.today(target)


@router.delete("/ledger/{pay_id}")
def ep_remove(pay_id: str):
    """오탐(비지출 오기록) 삭제."""
    ledger_mod.remove(pay_id)
    return {"ok": True}
