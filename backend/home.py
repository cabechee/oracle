"""홈 표지(front page) — 오늘의 상태를 한 번에 모은 조회 전용 모듈.

구성: 오늘 지금까지(기록 수·썸네일) · 오늘의 한 줄(어제 일기 발췌) ·
대신 읽어드림(최신 신호 brief) · 그날의 오늘(1주/1달 전 같은 날).
전부 기존 데이터 조회 — LLM 호출 없음(표지는 즉시 떠야 한다).
"""

import re
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional

import corpus
import db


def _day_range(d: date):
    return datetime.combine(d, dtime.min), datetime.combine(d, dtime.max)


def _first_sentence(body: str, limit: int = 120) -> str:
    """일기 본문에서 첫 의미 문장 — 헤더/빈 줄 건너뛰고 문장 1개."""
    for ln in (body or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = re.split(r"(?<=[.!?다요죠])\s", s, maxsplit=1)
        return parts[0][:limit]
    return ""


def _record_line(r: Dict[str, Any], limit: int = 60) -> str:
    """on-this-day 카드용 한 줄 — 유저 코멘트 우선, 없으면 인사이트 발췌."""
    uc = (r.get("user_comment") or "").strip()
    if uc:
        return uc[:limit]
    ins = ((r.get("insight") or {}).get("text") or "").strip()
    return ins[:limit]


def _thumb(r: Dict[str, Any]) -> Optional[str]:
    paths = r.get("image_paths") or []
    return corpus.to_vault_rel(paths[0]) if paths else None


def cover(target: Optional[date] = None) -> Dict[str, Any]:
    """홈 표지 — target(없으면 오늘) 날짜 기준. 과거 날짜도 같은 구조로 재현.

    달력에서 지난 날을 고르면 그날의 표지(기록·조간/석간·그날의 그날·신호)를 보여준다.
    """
    now = datetime.now()
    today = target or now.date()
    is_today = today == now.date()
    t0, t1 = _day_range(today)

    # 그날 기록 (오늘이면 '지금까지')
    todays = list(
        db.records().find(
            {"ts": {"$gte": t0, "$lte": t1}},
            {"_id": 1, "ts": 1, "image_paths": 1},
        ).sort("ts", -1))
    thumbs = [t for t in (_thumb(r) for r in todays) if t][:4]
    last_ts = todays[0]["ts"].isoformat() if todays else None

    # 그 전날로부터 한 줄 — 전날(없으면 그 전) 일기에서
    yesterday_line: Optional[Dict[str, str]] = None
    for back in (1, 2):
        d = today - timedelta(days=back)
        j = db.journals().find_one({"_id": f"day-{d.isoformat()}"})
        if not j:
            continue
        text = j.get("text", "")
        if "(일기 생성 실패" in text:
            continue  # 생성 실패한 날은 건너뜀 — 그 전날로 폴백
        # 세 줄 요약(자정 생성) 우선, 과거 일기(요약 없음)는 첫 문장 폴백
        line = (j.get("summary3") or "").strip() or _first_sentence(text)
        if line:
            yesterday_line = {"date": d.isoformat(), "text": line}
            break

    # 대신 읽어드림 — 오늘이면 최신 brief, 과거면 그날 brief
    if is_today:
        brief = db.signal_briefs().find_one(sort=[("ts", -1)])
    else:
        brief = db.signal_briefs().find_one(
            {"ts": {"$gte": t0, "$lte": t1}}, sort=[("ts", -1)])
    latest_brief = None
    if brief and (brief.get("summary") or "").strip():
        latest_brief = {
            "ts": brief["ts"].isoformat(),
            "summary": brief["summary"],
            "sms_count": brief.get("sms_count", 0),
            "call_count": brief.get("call_count", 0),
        }

    # 그날의 오늘 — target 기준 1주 전·1달 전 (사진 있는 기록 우선)
    on_this_day: List[Dict[str, Any]] = []
    for label, d in (("일주일 전", today - timedelta(days=7)),
                     ("한 달 전", today - timedelta(days=30))):
        r0, r1 = _day_range(d)
        rec = db.records().find_one(
            {"ts": {"$gte": r0, "$lte": r1}, "image_paths": {"$nin": [None, []]}},
            sort=[("ts", 1)],
        ) or db.records().find_one(
            {"ts": {"$gte": r0, "$lte": r1}}, sort=[("ts", 1)])
        if rec:
            on_this_day.append({
                "record_id": rec["_id"],
                "ts": rec["ts"].isoformat(),
                "label": label,
                "thumb": _thumb(rec),
                "line": _record_line(rec),
            })

    # 그날 지표 — 걸음 + 수면
    m = db.metrics().find_one({"_id": today.isoformat()})
    health = None
    if m and (m.get("steps") is not None or m.get("sleep_min") is not None):
        health = {"steps": m.get("steps"), "sleep_min": m.get("sleep_min")}

    # 발행물 — 그날 조간/석간 전부 (시간순). 과거 회고 시 둘 다 보인다.
    briefings = [
        {"kind": b.get("kind"), "text": b["text"],
         "ts": b["ts"].isoformat() if isinstance(b.get("ts"), datetime) else None}
        for b in db.briefings().find({"date": today.isoformat()}).sort("ts", 1)
        if (b.get("text") or "").strip()
    ]

    return {
        "date": today.isoformat(),
        "is_today": is_today,
        "today": {"count": len(todays), "last_ts": last_ts, "thumbs": thumbs},
        "briefings": briefings,
        "briefing": briefings[-1] if briefings else None,  # 구앱 호환 (단건)
        "yesterday_line": yesterday_line,
        "health": health,
        "latest_brief": latest_brief,
        "on_this_day": on_this_day,
    }
