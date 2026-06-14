"""홈 표지 라우터 — 앱 홈 탭이 한 번에 그리는 조회 전용 합성."""

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, HTTPException

import home as home_mod

router = APIRouter()


@router.get("/home/cover")
def ep_home_cover(date: Optional[str] = None):
    """date(YYYY-MM-DD) 주면 그날 표지, 없으면 오늘."""
    try:
        target = _date.fromisoformat(date) if date else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    try:
        return home_mod.cover(target)
    except Exception as e:
        raise HTTPException(500, str(e))
