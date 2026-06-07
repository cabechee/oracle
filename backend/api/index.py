"""상위 인덱스 라우터 — master.md + index_meta."""

from fastapi import APIRouter, HTTPException

import index as index_mod

router = APIRouter()


@router.get("/index/master")
def ep_index_master():
    """vault index/master.md — 사람용 검색 진입점 (자정 배치가 갱신)."""
    text = index_mod.read_master_index()
    if text is None:
        raise HTTPException(404, "master index 없음 — 자정 배치 한 번 이상 돌아야 생성")
    return {"text": text}


@router.get("/index/meta")
def ep_index_meta():
    """MongoDB index_meta 컬렉션 — 월별 통계(가벼운 구조 검색용)."""
    return {"months": index_mod.list_index_meta()}
