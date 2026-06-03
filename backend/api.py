"""FastAPI 라우터 — Layer 1 (인입 + 조회) + 사진 서빙 + Layer 3 (digest/threads) + Nest 상태."""

import os
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ingest as ingest_mod
import nest_client
import digest as digest_mod
import threads as threads_mod
import query as query_mod
from config import VAULT_DIR


router = APIRouter()


# ── Layer 1: 인입 + 조회 ───────────────────────────────────────

@router.post("/ingest")
def ep_ingest(
    file: Optional[UploadFile] = File(None),
    comment: Optional[str] = Form(None),
    model: Optional[str] = Form(None),   # Nest alias — 폰 UI에서 선택
):
    """캡처 인입 — 사진(file)·코멘트(comment) 중 하나 이상.

    model 비어있으면 TASK_ALIAS 디폴트 사용. 반환: {record_id, ts, insight, vlm_caption, vault_path, image_paths}.
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
        return ingest_mod.ingest(comment, image_bytes, image_ext, model=model)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── LLM alias 목록 (폰 UI 채우기용) ─────────────────────────────

@router.get("/llm/models")
def ep_llm_models():
    """Nest 등록 모델 + council alias. 토큰은 backend에만 — 폰에 노출 X."""
    try:
        return {
            "models": nest_client.list_models(),
            "councils": nest_client.list_councils(),
        }
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


# ── 사진 서빙 ───────────────────────────────────────────────────

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


# ── Layer 3: 자정 배치 (digest) ─────────────────────────────────

@router.post("/digest/run")
def ep_digest_run(target_date: Optional[str] = None):
    """수동 자정 배치 트리거 (dev/검증용).

    target_date='YYYY-MM-DD' 없으면 어제. thread_judge + type_classify + daily_digest 일괄 실행.
    """
    d = None
    if target_date:
        try:
            d = date_cls.fromisoformat(target_date)
        except Exception:
            raise HTTPException(400, "target_date 형식: YYYY-MM-DD")
    try:
        return digest_mod.run_daily(d)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/digest/list")
def ep_digest_list():
    """vault digest/ 안의 다이제스트 목록."""
    return {"items": digest_mod.list_digests()}


@router.get("/digest/{date_str}")
def ep_digest_get(date_str: str):
    """특정 날짜 다이제스트 마크다운."""
    text = digest_mod.read_digest(date_str)
    if text is None:
        raise HTTPException(404, "not found")
    return {"date": date_str, "text": text}


# ── Layer 3: thread 조회 ────────────────────────────────────────

@router.get("/threads")
def ep_threads_list(within_days: int = 60):
    """최근 N일 내 활동 있는 thread 목록."""
    return {"items": threads_mod.list_active_threads(within_days)}


@router.get("/threads/silent")
def ep_threads_silent(min_days: int = 5, max_days: int = 30):
    """min_days~max_days 무언급 thread (펜딩 환기 후보)."""
    return {"items": threads_mod.silent_threads(min_days, max_days)}


@router.get("/threads/{thread_id}")
def ep_threads_get(thread_id: int):
    """thread 메타 + 속한 record 타임라인."""
    t = threads_mod.get_thread(thread_id)
    if not t:
        raise HTTPException(404, "not found")
    return {**t, "records": threads_mod.list_thread_records(thread_id)}


# ── 자연어 검색·질의 ────────────────────────────────────────────

class QueryReq(BaseModel):
    question: str
    limit: int = 30


@router.post("/query")
def ep_query(body: QueryReq):
    """자연어 질문 → LLM이 vault·records·인덱스 보고 답변 + 참조 record_id."""
    if not body.question.strip():
        raise HTTPException(400, "question 비어있음")
    try:
        return query_mod.query(body.question.strip(), body.limit)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Layer 3: 상위 인덱스 ────────────────────────────────────────

@router.get("/index/master")
def ep_index_master():
    """vault index/master.md — 사람용 검색 진입점 (자정 배치가 갱신)."""
    text = digest_mod.read_master_index()
    if text is None:
        raise HTTPException(404, "master index 없음 — 자정 배치 한 번 이상 돌아야 생성")
    return {"text": text}


@router.get("/index/meta")
def ep_index_meta():
    """MongoDB index_meta 컬렉션 — 월별 통계(가벼운 구조 검색용)."""
    return {"months": digest_mod.list_index_meta()}


# ── Nest 상태 확인 (디버그) ─────────────────────────────────────

@router.get("/nest/health")
def ep_nest_health():
    """Nest 게이트웨이 도달 가능 여부."""
    try:
        return {"ok": True, "nest": nest_client.health()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
