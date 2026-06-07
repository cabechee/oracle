"""record 라우터 — 리액션·편집·목록·단건 + 사진 서빙."""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ingest as ingest_mod
from config import VAULT_DIR

router = APIRouter()


class ReactionBody(BaseModel):
    reaction: str   # "interesting" | "useful" | "skip" 등 자유 텍스트


@router.post("/records/{record_id}/reaction")
def ep_reaction(record_id: str, body: ReactionBody):
    ok = ingest_mod.set_reaction(record_id, body.reaction)
    if not ok:
        raise HTTPException(404, "record not found")
    return {"ok": True}


class RecordPatch(BaseModel):
    user_comment: Optional[str] = None


@router.patch("/records/{record_id}")
def ep_patch_record(record_id: str, body: RecordPatch):
    """record 부분 수정. 현재는 user_comment 만 지원 (잘못 보낸 거 정정).
    vault 평문은 append-only — Mongo만 갱신."""
    changed = False
    if body.user_comment is not None:
        if ingest_mod.update_comment(record_id, body.user_comment):
            changed = True
        else:
            raise HTTPException(404, "record not found")
    return {"ok": True, "changed": changed}


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


@router.get("/photos/{path:path}")
def ep_photo(path: str):
    """vault 기준 상대경로로 사진 서빙.
    예: GET /photos/images/2026/06/03-081214-1.jpg
    vault 밖 경로는 거부 (path traversal 방지).
    """
    full = os.path.join(VAULT_DIR, path)
    real_full = os.path.realpath(full)
    real_vault = os.path.realpath(VAULT_DIR)
    if not (real_full == real_vault or real_full.startswith(real_vault + os.sep)):
        raise HTTPException(403, "outside vault")
    if not os.path.isfile(real_full):
        raise HTTPException(404, "not found")
    return FileResponse(real_full)
