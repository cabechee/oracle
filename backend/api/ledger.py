"""가계부 라우터 — 조회 · 결산 · 거래내역(장부) · 영수증 드롭 · 확인필요 채우기 · 삭제."""

import datetime
import hashlib
import os
import tempfile
from datetime import date as _date
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import category as category_mod
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


def _pdf_to_pngs(data: bytes, max_pages: int = 30, dpi: int = 150) -> list:
    """PDF 바이트 → 페이지별 PNG 바이트. pymupdf(fitz) 사용. 실패/미설치면 []."""
    try:
        import fitz
    except Exception:
        return []
    out = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        for i in range(min(doc.page_count, max_pages)):
            out.append(doc[i].get_pixmap(dpi=dpi).tobytes("png"))
        doc.close()
    except Exception as e:
        print(f"[ledger] PDF 변환 실패: {e}", flush=True)
    return out


@router.post("/ledger/receipt")
async def ep_receipt(file: UploadFile = File(...)):
    """영수증 드롭 → 비전 인식 → 가계부 매칭(merge). 어드민 드래그&드랍 + 수집기 공유 분류기.

    **PDF(여러 장 묶음)·여러 영수증** 지원: 페이지별로 변환해 각 영수증을 따로 매칭/기록.
    같은 금액·날짜의 카드알림이 있으면 합쳐 보강, 없으면 새 항목.
    """
    data = await file.read()
    return process_receipt_image(data, file.filename or "")


def process_receipt_image(data: bytes, filename: str) -> dict:
    """영수증 이미지/PDF → ledger 매칭. 어드민 드롭·공유 분류기(/share/image) 공용."""
    if not data:
        raise HTTPException(400, "빈 파일")
    import corpus
    import ingest
    import nest_client
    from agent import vision
    now = datetime.datetime.now()
    fname = (filename or "").lower()
    is_pdf = fname.endswith(".pdf") or data[:5] == b"%PDF-"
    # 페이지(또는 단일 이미지)별로 vault에 저장
    pages = []   # [(vault_rel, abs_path)]
    if is_pdf:
        corpus.save_image(now, 0, data, "pdf")     # 원본 PDF 보존 — 처리 중단(재시작) 시 재드롭으로 멱등 복구
        pngs = _pdf_to_pngs(data)
        if not pngs:
            raise HTTPException(400, "PDF를 이미지로 변환하지 못했어요(pymupdf 필요)")
        for i, pb in enumerate(pngs, 1):
            ap = corpus.save_image(now, i, pb, "png")
            pages.append((corpus.to_vault_rel(ap), ap))
    else:
        ext = os.path.splitext(fname)[1].lstrip(".") or "jpg"
        ap = corpus.save_image(now, 1, data, ext)
        pages.append((corpus.to_vault_rel(ap), ap))
    alias = ingest._resolve_alias("vision", None, prefer_vision=True, fallback_key="insight")
    h = hashlib.sha1(data).hexdigest()[:10]
    results = []
    idx = 0
    for vault_rel, ap in pages:        # 페이지마다 영수증 전부 추출(한 장에 여러 건도)
        for rc in vision.extract_receipts(alias, nest_client.images_from_paths([ap])):
            # 안정적 id(승인번호+금액) — 같은 영수증 재처리해도 중복/이중합산 방지
            rid = (f"drop-{rc.get('approval')}-{rc.get('total')}"
                   if rc.get("approval") else f"drop-{h}-{idx}")
            res = ledger_mod.from_receipt(rid, now, {
                "amount": rc.get("total"), "merchant": rc.get("merchant"),
                "items": rc.get("items"), "date": rc.get("date"),
                "method": rc.get("method"), "approval": rc.get("approval"),
                "rtype": rc.get("rtype"), "platform": rc.get("platform"), "image": vault_rel})
            results.append({"merchant": rc.get("merchant"), "amount": rc.get("total"),
                            "result": res})
            idx += 1
    if not results:
        return {"ok": False, "reason": "영수증을 찾지 못했어요", "pages": len(pages)}
    merged = sum(1 for r in results if r["result"] == "merged")
    return {"ok": True, "count": len(results), "merged": merged,
            "pages": len(pages), "items": results}


@router.post("/ledger/{pay_id}/receipt")
async def ep_entry_receipt(pay_id: str, file: UploadFile = File(...)):
    """**특정 항목**에 영수증 붙이기 — 자동 매칭 없이 내가 고른 항목에. 비전이 읽으면 가맹점·품목도
    채우고, 못 읽어도 이미지는 그 항목에 붙는다(가맹점은 수동 입력으로 채울 수 있음)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "빈 파일")
    import corpus
    import ingest
    import nest_client
    from agent import vision
    now = datetime.datetime.now()
    ext = os.path.splitext(file.filename or "")[1].lstrip(".") or "jpg"
    abs_path = corpus.save_image(now, 1, data, ext)
    vault_rel = corpus.to_vault_rel(abs_path)
    alias = ingest._resolve_alias("vision", None, prefer_vision=True, fallback_key="insight")
    f = vision.extract_receipt(alias, nest_client.images_from_paths([abs_path]))
    fields = {"image": vault_rel}
    recognized = isinstance(f, dict) and f.get("is_receipt")
    if recognized:
        fields.update({"merchant": f.get("merchant"), "items": f.get("items"),
                       "method": f.get("method"), "approval": f.get("approval")})
    row = ledger_mod.attach_receipt(pay_id, fields)
    if row is None:
        raise HTTPException(404, "항목 없음")
    return {"ok": True, "item": row, "recognized": bool(recognized)}


@router.get("/ledger/categories")
def ep_categories():
    """분류 체계 + 등록된 규칙 — 어드민 수정 드롭다운·규칙 관리용."""
    category_mod.seed()
    return {"categories": category_mod.CATEGORIES, "rules": category_mod.list_rules()}


class RuleIn(BaseModel):
    name: str
    pattern: str
    category: str
    fields: Optional[List[str]] = None
    set_merchant: str = ""
    priority: int = 50
    id: Optional[str] = None


@router.post("/ledger/rules")
def ep_upsert_rule(body: RuleIn):
    """분류 규칙 추가/수정."""
    return category_mod.upsert_rule(body.name, body.pattern, body.category,
                                    fields=body.fields, set_merchant=body.set_merchant,
                                    priority=body.priority, rule_id=body.id)


@router.delete("/ledger/rules/{rule_id}")
def ep_delete_rule(rule_id: str):
    return {"ok": category_mod.delete_rule(rule_id)}


@router.post("/ledger/recategorize")
def ep_recategorize():
    """규칙을 모든 지출에 재적용(분류 + 가맹점 보정)."""
    category_mod.seed()
    return {"ok": True, "changed": category_mod.recategorize()}


@router.post("/ledger/upgrade")
def ep_upgrade():
    """LLM 주기 업그레이드 — 규칙 없는 가맹점을 품목 보고 분류 → 규칙 등록 → 재분류."""
    import ingest
    alias = ingest._resolve_alias("classify", None, prefer_vision=False, fallback_key="insight")
    return category_mod.upgrade(alias)


class AmountIn(BaseModel):
    amount: int


@router.post("/ledger/{pay_id}/amount")
def ep_resolve_diff(pay_id: str, body: AmountIn):
    """금액 불일치(diff) 판독 — 고른 금액으로 확정, diff 해제."""
    return {"ok": ledger_mod.resolve_diff(pay_id, body.amount)}


class CatIn(BaseModel):
    category: str


@router.post("/ledger/{pay_id}/category")
def ep_set_category(pay_id: str, body: CatIn):
    """거래 분류 수정 — 그 가맹점 규칙도 즉시 학습(규칙 없던 가맹점이면 생성·재분류)."""
    return ledger_mod.set_category_learn(pay_id, body.category)


class FieldsIn(BaseModel):
    merchant: Optional[str] = None
    category: Optional[str] = None
    method: Optional[str] = None
    kind: Optional[str] = None
    memo: Optional[str] = None
    items: Optional[List[str]] = None    # 내역(품목) 수정 — 어드민 거래내역 📝


@router.post("/ledger/{pay_id}")
def ep_set_fields(pay_id: str, body: FieldsIn):
    """확인필요 항목 채우기 — 가맹점·카테고리 등. needs/complete 재계산."""
    return {"ok": ledger_mod.set_fields(pay_id, body.model_dump(exclude_none=True))}


@router.delete("/ledger/{pay_id}")
def ep_remove(pay_id: str):
    """오탐(비지출 오기록) 삭제."""
    ledger_mod.remove(pay_id)
    return {"ok": True}
