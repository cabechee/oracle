"""홈 표지 라우터 — 앱 홈 탭이 한 번에 그리는 조회 전용 합성."""

from fastapi import APIRouter, HTTPException

import home as home_mod

router = APIRouter()


@router.get("/home/cover")
def ep_home_cover():
    try:
        return home_mod.cover()
    except Exception as e:
        raise HTTPException(500, str(e))
