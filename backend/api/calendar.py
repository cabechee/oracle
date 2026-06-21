"""캘린더 라우터 — 다가오는 일정·오늘 일정·이벤트 생성 + 인증 상태 + 스크린샷 인식."""

import re
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import gcal

router = APIRouter()


def _hhmm(t: Optional[str]) -> Optional[str]:
    """'14:30'·'2:5' 등 → 'HH:MM'. 시간 못 읽으면 None."""
    m = re.search(r"(\d{1,2}):(\d{2})", (t or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h % 24:02d}:{mi % 60:02d}"


@router.get("/calendar/status")
def ep_status():
    """인증 상태 — 어드민 캘린더 페이지·앱이 '연동됨?' 판단."""
    return gcal.status()


@router.get("/calendar/upcoming")
def ep_upcoming(days: int = 7):
    """지금부터 days일 일정(시작순). 미인증이면 items=[]·authed=False."""
    return {"items": gcal.upcoming(days=days), "authed": gcal.is_authed()}


@router.get("/calendar/today")
def ep_today():
    """오늘 일정 + 한 줄 표현(동반자·일기 배경 재료)."""
    return {"items": gcal.today_events(), "lines": gcal.day_lines()}


class EventIn(BaseModel):
    title: str
    start: str                       # ISO8601(시각) 또는 YYYY-MM-DD(종일)
    end: Optional[str] = None
    description: str = ""
    location: str = ""
    all_day: bool = False


@router.post("/calendar/events")
def ep_create(body: EventIn):
    """이벤트 생성 — 기록/리마인더를 일정으로 올릴 때. 미인증이면 503."""
    if not body.title.strip() or not body.start.strip():
        raise HTTPException(400, "title·start 필요")
    ev = gcal.create_event(body.title, body.start, body.end,
                           body.description, body.location, body.all_day)
    if ev is None:
        raise HTTPException(503, "캘린더 미인증 또는 생성 실패")
    return ev


@router.post("/calendar/screenshot")
async def ep_screenshot(file: UploadFile = File(...)):
    """스크린샷/이미지 드롭 → 비전 일정 인식 → 캘린더 등록. 어드민 드래그&드랍용(여러 일정 OK)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "빈 파일")
    if not gcal.is_authed():
        raise HTTPException(503, "캘린더 미인증")
    import datetime as _dt

    import corpus
    import ingest
    import nest_client
    from agent import vision
    now = _dt.datetime.now()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    ap = corpus.save_image(now, 1, data, ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg")
    alias = ingest._resolve_alias("vision", None, prefer_vision=True, fallback_key="insight")
    evs = vision.extract_calendar_events(
        alias, nest_client.images_from_paths([ap]), today=now.strftime("%Y-%m-%d"))
    created = []
    for ev in evs:
        title = (ev.get("title") or "").strip()
        d = (ev.get("date") or "").strip()
        if not title or not re.match(r"\d{4}-\d{2}-\d{2}", d):
            continue
        st = _hhmm(ev.get("start"))
        all_day = bool(ev.get("all_day")) or not st
        if all_day:
            start, end = d[:10], None
        else:
            start = f"{d[:10]}T{st}:00+09:00"
            en = _hhmm(ev.get("end"))
            if not en:                                    # 종료 없으면 +1시간(자정 넘김 방지)
                h = int(st[:2])
                en = f"{h + 1:02d}:{st[3:]}" if h < 23 else None
            end = f"{d[:10]}T{en}:00+09:00" if en else None
        res = gcal.create_event(title, start, end,
                                (ev.get("description") or "").strip(),
                                (ev.get("location") or "").strip(), all_day)
        if res:
            created.append({"title": title, "date": d[:10],
                            "time": None if all_day else st, "location": ev.get("location") or ""})
    if not created:
        return {"ok": False, "reason": "일정을 찾지 못했어요"}
    return {"ok": True, "count": len(created), "events": created}
