"""가계부 라우터 — 조회 · 결산 · 확인필요 채우기 · 오기록 삭제."""

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import ledger as ledger_mod

router = APIRouter()


@router.get("/ledger")
def ep_today(date: Optional[str] = None):
    """그날(기본 오늘) 가계부 — 수입/지출 합·항목."""
    try:
        target = _date.fromisoformat(date) if date else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return ledger_mod.today(target)


@router.get("/ledger/settlement")
def ep_settlement(period: str = "month", date: Optional[str] = None):
    """주/월 결산 — 수입·지출·순액 + 카테고리/결제수단/상위가맹점/반복 (대차대조표용)."""
    try:
        target = _date.fromisoformat(date) if date else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return ledger_mod.settlement(period, target)


@router.get("/ledger/incomplete")
def ep_incomplete():
    """정보 부족(가맹점 등) 항목 — 데스크 '지출내역 확인필요'."""
    return {"items": ledger_mod.incomplete()}


class FieldsIn(BaseModel):
    merchant: Optional[str] = None
    category: Optional[str] = None
    method: Optional[str] = None
    kind: Optional[str] = None
    memo: Optional[str] = None


@router.post("/ledger/{pay_id}")
def ep_set_fields(pay_id: str, body: FieldsIn):
    """확인필요 항목 채우기 — 가맹점·카테고리 등. needs/complete 재계산."""
    return {"ok": ledger_mod.set_fields(pay_id, body.model_dump(exclude_none=True))}


@router.delete("/ledger/{pay_id}")
def ep_remove(pay_id: str):
    """오탐(비지출 오기록) 삭제."""
    ledger_mod.remove(pay_id)
    return {"ok": True}
