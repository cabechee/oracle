"""FastAPI 라우터 — Layer 1 (인입 + 조회) + Nest 상태."""

from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

import ingest as ingest_mod
import nest_client


router = APIRouter()


# ── Layer 1: 인입 + 조회 ───────────────────────────────────────

@router.post("/ingest")
def ep_ingest(
    file: Optional[UploadFile] = File(None),
    comment: Optional[str] = Form(None),
):
    """캡처 인입 — 사진(file)·코멘트(comment) 중 하나 이상.

    반환: {record_id, ts, insight, vlm_caption, vault_path, image_paths}.
    """
    image_bytes: Optional[bytes] = None
    image_ext = "jpg"
    if file is not None:
        image_bytes = file.file.read()
        if file.filename and "." in file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in ("jpg", "jpeg", "png", "webp", "heic"):
                image_ext = "jpg" if ext == "jpeg" else ext

    if not image_bytes and not comment:
        raise HTTPException(400, "file 또는 comment 중 하나 이상 필요")

    try:
        return ingest_mod.ingest(comment, image_bytes, image_ext)
    except Exception as e:
        raise HTTPException(500, str(e))


class ReactionBody(BaseModel):
    reaction: str   # "interesting" | "useful" | "skip" 등 자유 텍스트


@router.post("/records/{record_id}/reaction")
def ep_reaction(record_id: str, body: ReactionBody):
    ok = ingest_mod.set_reaction(record_id, body.reaction)
    if not ok:
        raise HTTPException(404, "record not found")
    return {"ok": True}


@router.get("/records")
def ep_list_records(limit: int = 50, offset: int = 0):
    """최근 Record 목록 (채팅 무한스크롤)."""
    return {"items": ingest_mod.list_recent(limit, offset)}


@router.get("/records/{record_id}")
def ep_get_record(record_id: str):
    r = ingest_mod.get_record(record_id)
    if not r:
        raise HTTPException(404, "not found")
    return r


# ── Nest 상태 확인 (디버그) ─────────────────────────────────────

@router.get("/nest/health")
def ep_nest_health():
    """Nest 게이트웨이 도달 가능 여부."""
    try:
        return {"ok": True, "nest": nest_client.health()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
