"""thread 조회 라우터."""

from fastapi import APIRouter, HTTPException

import threads as threads_mod

router = APIRouter()


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
