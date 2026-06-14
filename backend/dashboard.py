"""데스크 — '확인하면 사라지는' 처리 대시보드 (온라인 오라클).

홈 표지(오늘 탭)가 '읽을 거리'라면, 데스크는 '처리할 거리'다.
신호의 당장 액션, 오래 못 챙긴 사람처럼 — 확인·처리하면 목록에서 빠져야 하는
것들을 모은다. dismiss(확인 처리)는 dashboard_state 컬렉션에 키로 기록되어
재조회 시 제외된다.

전부 조회 전용(+ dismiss 1건 쓰기). LLM 호출 없음 — 데스크도 즉시 떠야 한다.
"""

from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Set

import db

_ACTION_WINDOW_DAYS = 7        # 이 안의 당장 액션만 (그 전은 자연 소멸)
_PENDING_MIN, _PENDING_MAX = 5, 30


# ── 키 (dismiss 식별자) ─────────────────────────────────────────

def _action_key(brief_id: str, idx: int) -> str:
    """당장 처리 항목 키 — brief + 항목 인덱스로 고유."""
    return f"action:{brief_id}#{idx}"


def _pending_key(thread_id: Any) -> str:
    """오래 못 챙긴 사람 키 — thread 단위."""
    return f"pending:{thread_id}"


# ── 순수 변환 (db 불요 — 테스트 대상) ───────────────────────────

def _collect_actions(briefs: List[Dict[str, Any]],
                     dismissed: Set[str]) -> List[Dict[str, Any]]:
    """brief 목록 → 당장 처리 항목. dismiss·부정확 표시는 제외.

    순수 함수(외부 의존 없음) — 데스크의 핵심 필터 로직을 여기서 검증한다.
    """
    out: List[Dict[str, Any]] = []
    seen_sids: Set[str] = set()      # 이미 담은 원본 신호 (다른 brief 중복 요약 차단)
    seen_text: Set[tuple] = set()    # signal_id 없는 구 brief는 발신자+요약으로
    for b in briefs:
        bid = b.get("_id")
        ts = b.get("ts")
        for idx, it in enumerate(b.get("items") or []):
            if it.get("category") != "action_needed":
                continue
            if it.get("feedback") == "inaccurate":
                continue              # 유저가 '부정확' 표시한 분류는 띄우지 않음
            key = _action_key(bid, idx)
            if key in dismissed:
                continue              # 이미 확인 처리됨 → 사라짐
            sids = [s for s in (it.get("signal_ids") or []) if s]
            if any(s in seen_sids for s in sids):
                continue              # 같은 원본 신호 — race로 다른 brief에 중복된 것
            sender = (it.get("sender") or "").strip()
            summary = (it.get("summary") or "").strip()
            if not sids and (sender, summary) in seen_text:
                continue
            seen_sids.update(sids)
            seen_text.add((sender, summary))
            out.append({
                "key": key,
                "brief_id": bid,
                "sender": sender,
                "summary": summary,
                "ts": ts.isoformat() if isinstance(ts, datetime) else None,
            })
    return out


# ── 조회 ────────────────────────────────────────────────────────

def _dismissed_keys() -> Set[str]:
    return {
        d["_id"]
        for d in db.dashboard_state().find(
            {"dismissed_at": {"$ne": None}}, {"_id": 1})
    }


def _day_range(d):
    return datetime.combine(d, dtime.min), datetime.combine(d, dtime.max)


def feed() -> Dict[str, Any]:
    """데스크 전체 — 당장 처리 · 대신 읽어드림 · 오래 못 챙긴 사람 · 오늘 정리."""
    now = datetime.now()
    today = now.date()
    dismissed = _dismissed_keys()

    # 1) 당장 처리 — 최근 N일 brief의 action_needed (확인 안 한 것만)
    briefs = list(db.signal_briefs().find(
        {"ts": {"$gte": now - timedelta(days=_ACTION_WINDOW_DAYS)}}
    ).sort("ts", -1))
    actions = _collect_actions(briefs, dismissed)

    # 2) 대신 읽어드림 — 오늘 받은 알림을 발신자별로 묶어 누적 요약 (실시간, 안 날림)
    import signals as signals_mod
    digest = signals_mod.today_digest()

    # 2b) 가계부 — 오늘 결제(스마트 액션)
    import ledger as ledger_mod
    today_ledger = ledger_mod.today()

    # 2c) 리마인더 — 자체(미완료)
    import reminders as reminders_mod
    reminder_list = reminders_mod.list_items()

    # 3) 오래 못 챙긴 사람 — silent thread (확인 안 한 것만)
    import threads as threads_mod
    pending: List[Dict[str, Any]] = []
    for t in threads_mod.silent_threads(_PENDING_MIN, _PENDING_MAX):
        key = _pending_key(t["id"])
        if key in dismissed:
            continue
        pending.append({**t, "key": key})

    # 4) 오늘 정리 — 내 활동을 데이터로 (기록·사진·이번 주·신호)
    t0, t1 = _day_range(today)
    week0 = datetime.combine(today - timedelta(days=6), dtime.min)
    today_stats = {
        "records": db.records().count_documents({"ts": {"$gte": t0, "$lte": t1}}),
        "photos": db.records().count_documents(
            {"ts": {"$gte": t0, "$lte": t1}, "image_paths": {"$nin": [None, []]}}),
        "week_records": db.records().count_documents(
            {"ts": {"$gte": week0, "$lte": t1}}),
        "signals_today": db.signals().count_documents(
            {"ts": {"$gte": t0, "$lte": t1}}),
    }

    return {
        "actions": actions,
        "digest": digest,            # 대신 읽어드림 (발신자별 누적 요약)
        "ledger": today_ledger,      # 가계부 (오늘 결제)
        "reminders": reminder_list,  # 자체 리마인더
        "pending_people": pending,
        "today": today_stats,
        "counts": {"actions": len(actions), "pending": len(pending),
                   "reminders": len(reminder_list)},
    }


def dismiss(key: str) -> bool:
    """항목 확인 처리 — 재조회 시 제외. key='action:...' | 'pending:...'."""
    if not key:
        return False
    db.dashboard_state().update_one(
        {"_id": key},
        {"$set": {"dismissed_at": datetime.now()}},
        upsert=True,
    )
    return True
