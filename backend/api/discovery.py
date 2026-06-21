"""발견 라우터 — 메뉴별 오늘 발견(상단 quote) + 닫기 + 로그 + 수동 생성."""

from fastapi import APIRouter

import discovery as disco

router = APIRouter()


@router.get("/discovery/log")
def ep_log(limit: int = 80):
    """발견 로그 전체(최신순) — 어드민 '발견' 메뉴."""
    return {"items": disco.log(limit)}


@router.post("/discovery/run")
def ep_run():
    """발견 수동 생성(자정 배치와 동일) — 지금 한 번 돌림."""
    return disco.generate_all()


@router.get("/discovery/{menu}")
def ep_today(menu: str):
    """그 메뉴의 오늘 발견(확인 안 한 것). 없으면 빈 객체."""
    return disco.today(menu) or {}


@router.post("/discovery/{menu}/dismiss")
def ep_dismiss(menu: str):
    """오늘 그 메뉴 발견 닫기."""
    return {"ok": disco.dismiss(menu)}
