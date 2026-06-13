"""저널·다이제스트 라우터 — 자정 배치 트리거 + 주/월 회고 + 조회."""

from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, HTTPException

import nightly
import journal as journal_svc

router = APIRouter()


def _parse_date(target_date: Optional[str]):
    if not target_date:
        return None
    try:
        return date_cls.fromisoformat(target_date)
    except Exception:
        raise HTTPException(400, "target_date 형식: YYYY-MM-DD")


@router.post("/digest/run")
def ep_digest_run(target_date: Optional[str] = None):
    """자정 배치 트리거 (launchd plist가 호출 + dev/검증용).

    target_date='YYYY-MM-DD' 지정 → 그 날 일 저널만 재생성.
    미지정(실제 자정 run) → run_nightly: 어제 일 저널 + (월요일)주간 + (1일)월간.
    """
    d = _parse_date(target_date)
    try:
        return nightly.run_daily(d) if d else nightly.run_nightly()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/journal/weekly")
def ep_journal_weekly(target_date: Optional[str] = None):
    """주간 회고 수동 트리거. target_date(그 주의 아무 날) 없으면 지난 주."""
    d = _parse_date(target_date)
    try:
        return journal_svc.run_weekly(d)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/journal/monthly")
def ep_journal_monthly(target_date: Optional[str] = None):
    """월간 회고 수동 트리거. target_date(그 달의 아무 날) 없으면 지난 달."""
    d = _parse_date(target_date)
    try:
        return journal_svc.run_monthly(d)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/journal/list")
def ep_journal_list(kind: Optional[str] = None):
    """journals 목록(메타만). kind=day|week|month 필터 가능."""
    return {"items": journal_svc.list_journals(kind)}


@router.get("/journal/{jid}")
def ep_journal_get(jid: str):
    """journals 단건 본문."""
    j = journal_svc.read_journal(jid)
    if j is None:
        raise HTTPException(404, "not found")
    return j


@router.get("/digest/list")
def ep_digest_list():
    """vault digest/ 안의 다이제스트 목록."""
    return {"items": journal_svc.list_digests()}


@router.get("/digest/{date_str}")
def ep_digest_get(date_str: str):
    """특정 날짜 다이제스트 마크다운."""
    d = _parse_date(date_str)   # 날짜 형식 강제 — 임의 문자열로 파일명 조합 차단
    text = journal_svc.read_digest(d.isoformat())
    if text is None:
        raise HTTPException(404, "not found")
    return {"date": d.isoformat(), "text": text}
