"""건강 지표 라우터 — 앱이 Health Connect에서 읽은 수면·걸음 동기화."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db

router = APIRouter()


class MetricsBody(BaseModel):
    date: str                          # YYYY-MM-DD (오늘 — 걸음, 어젯밤 수면 기준)
    sleep_min: Optional[int] = None    # 어젯밤 총 수면(분)
    steps: Optional[int] = None        # 오늘 누적 걸음


@router.post("/metrics/sync")
def ep_metrics_sync(body: MetricsBody):
    """일별 지표 upsert. 부분 갱신(있는 값만) — 걸음은 하루 종일 늘어남."""
    setter = {"updated_at": datetime.now()}
    if body.sleep_min is not None:
        setter["sleep_min"] = body.sleep_min
    if body.steps is not None:
        setter["steps"] = body.steps
    try:
        db.metrics().update_one(
            {"_id": body.date}, {"$set": setter}, upsert=True)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}
