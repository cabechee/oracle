"""자체 리마인더 — 외부 앱 연동 없이 Oracle 내부에서 관리.

위젯 아래 절반·데스크에서 보이는 할 일. 사용자가 직접 추가하거나, 신호의
'당장 액션'(action_needed)을 리마인더로 승격할 수 있다(source=signal). 가벼운 CRUD.
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import db


def _rid(text: str, signal_id: Optional[str]) -> str:
    seed = signal_id or f"{text}-{datetime.now().isoformat()}"
    return "rem-" + hashlib.sha1(seed.encode()).hexdigest()[:12]


def add(text: str, due: Optional[str] = None, source: str = "manual",
        signal_id: Optional[str] = None) -> str:
    """리마인더 추가. signal_id 있으면 그걸로 멱등(같은 신호 두 번 승격 방지)."""
    text = (text or "").strip()
    if not text:
        return ""
    rid = _rid(text, signal_id)
    doc = {
        "_id": rid,
        "text": text,
        "due": due,                  # ISO 문자열 또는 None
        "done": False,
        "source": source,            # manual | signal
        "signal_id": signal_id,
        "created": datetime.now(),
    }
    db.reminders().update_one({"_id": rid}, {"$setOnInsert": doc}, upsert=True)
    return rid


def _view(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["_id"],
        "text": r.get("text", ""),
        "due": r.get("due"),
        "done": bool(r.get("done")),
        "source": r.get("source", "manual"),
        "created": r["created"].isoformat()
        if isinstance(r.get("created"), datetime) else None,
    }


def list_items(include_done: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
    """리마인더 목록 — 미완료 우선, 최근 추가 순. include_done이면 완료분도."""
    q: Dict[str, Any] = {} if include_done else {"done": {"$ne": True}}
    rows = db.reminders().find(q).sort("created", -1).limit(limit)
    return [_view(r) for r in rows]


def set_done(rid: str, done: bool = True) -> bool:
    return db.reminders().update_one(
        {"_id": rid}, {"$set": {"done": done}}).matched_count > 0


def remove(rid: str) -> bool:
    return db.reminders().delete_one({"_id": rid}).deleted_count > 0


def active_count() -> int:
    return db.reminders().count_documents({"done": {"$ne": True}})
