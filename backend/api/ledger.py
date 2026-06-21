"""가계부 라우터 — 조회 · 결산 · 거래내역(장부) · 영수증 드롭 · 확인필요 채우기 · 삭제."""

import datetime
import hashlib
import os
import tempfile
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
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
    """주/월 결산 — 수입·지출·순액 + 카테고리/결제수단/상위가맹점/반복 (대차대조표 요약)."""
    try:
        target = _date.fromisoformat(date) if date else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return ledger_mod.settlement(period, target)


@router.get("/ledger/list")
def ep_list(period: str = "month", date: Optional[str] = None):
    """기간 전체 거래내역(장부, 시간순) — 어드민 대차대조표 상세."""
    try:
        target = _date.fromisoformat(date) if date else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    return {"items": ledger_mod.entries(period, target)}


@router.get("/ledger/incomplete")
def ep_incomplete():
    """정보 부족(가맹점 등) 항목 — 데스크 '지출내역 확인필요'."""
    return {"items": ledger_mod.incomplete()}


@router.post("/ledger/receipt")
async def ep_receipt(file: UploadFile = File(...)):
    """영수증 이미지 드롭 → 비전 인식 → 가계부 매칭(merge). 어드민 드래그&드랍용.

    같은 금액·날짜의 카드알림이 있으면 합쳐 보강, 없으면 새 항목.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "빈 파일")
    import corpus
    import ingest
    import nest_client
    from agent import vision
    now = datetime.datetime.now()
    ext = os.path.splitext(file.filename or "")[1].lstrip(".") or "jpg"
    abs_path = corpus.save_image(now, 1, data, ext)        # vault에 영구 저장(나중에 열람)
    vault_rel = corpus.to_vault_rel(abs_path)
    alias = ingest._resolve_alias("vision", None, prefer_vision=True, fallback_key="insight")
    f = vision.extract_receipt(alias, nest_client.images_from_paths([abs_path]))
    if not (isinstance(f, dict) and f.get("is_receipt") and f.get("total")):
        return {"ok": False, "reason": "영수증으로 인식하지 못했어요",
                "image": vault_rel, "extracted": f}
    h = hashlib.sha1(data).hexdigest()[:12]
    res = ledger_mod.from_receipt(f"receipt-drop-{h}", now, {
        "amount": f.get("total"), "merchant": f.get("merchant"), "items": f.get("items"),
        "date": f.get("date"), "method": f.get("method"), "image": vault_rel})
    return {"ok": True, "result": res, "merchant": f.get("merchant"), "amount": f.get("total"),
            "method": f.get("method"), "items": f.get("items"), "image": vault_rel}


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
