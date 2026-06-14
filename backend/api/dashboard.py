"""데스크 라우터 — 처리 대시보드 조회 + 확인(dismiss)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import dashboard as dashboard_mod

router = APIRouter()


@router.get("/dashboard")
def ep_dashboard():
    """데스크 — 당장 처리·대신 읽어드림·오래 못 챙긴 사람·오늘 정리."""
    try:
        return dashboard_mod.feed()
    except Exception as e:
        raise HTTPException(500, str(e))


class DismissBody(BaseModel):
    key: str          # 'action:brief-...#0' | 'pending:3'


@router.post("/dashboard/dismiss")
def ep_dashboard_dismiss(body: DismissBody):
    """항목 확인 처리 — 데스크에서 사라진다."""
    if not dashboard_mod.dismiss(body.key):
        raise HTTPException(400, "key required")
    return {"ok": True}
