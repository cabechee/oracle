"""Nest 게이트웨이 상태 확인 라우터 (디버그)."""

from fastapi import APIRouter

import nest_client

router = APIRouter()


@router.get("/nest/health")
def ep_nest_health():
    """Nest 게이트웨이 도달 가능 여부."""
    try:
        return {"ok": True, "nest": nest_client.health()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
