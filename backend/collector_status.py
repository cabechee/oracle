"""수집기 라이브 상태 — 현재 WiFi·위치·BT + 최근 로그 (수집기가 매 사이클 보고).

adb 없이 어드민 📍 장소에서 '지금 무슨 WiFi에 물렸나·어디 있다고 보나·무슨 일이 있었나'를
본다. 운전 중 BT·동반자 동작 확인(logcat 대체)에 특히 — 폰 브라우저로 /admin 열어 확인.
단순 1-doc 저장(settings['collector_status']). 라이브 상태라 히스토리는 안 쌓는다(덮어씀).
"""

from datetime import datetime
from typing import Any, Dict, List

import db

_MAX_LOGS = 120


def report(data: Dict[str, Any]) -> Dict[str, Any]:
    """수집기 보고 — 현재 상태 + 최근 로그로 덮어쓴다. 반환=정규화된 view."""
    logs: List[str] = [str(x) for x in (data.get("logs") or [])][-_MAX_LOGS:]
    doc = {
        "device_id": str(data.get("device_id") or ""),
        "wifi": str(data.get("wifi") or ""),
        "place": str(data.get("place") or ""),
        "visit_on": bool(data.get("visit_on")),
        "bt": str(data.get("bt") or ""),
        "logs": logs,
        "updated_at": datetime.now(),
    }
    db.settings().update_one({"_id": "collector_status"}, {"$set": doc}, upsert=True)
    return view()


def view() -> Dict[str, Any]:
    """어드민 표시용 — 현재 상태 + '몇 초 전 보고' 신선도."""
    d = db.settings().find_one({"_id": "collector_status"}) or {}
    up = d.get("updated_at")
    return {
        "device_id": d.get("device_id", ""),
        "wifi": d.get("wifi", ""),
        "place": d.get("place", ""),
        "visit_on": bool(d.get("visit_on")),
        "bt": d.get("bt", ""),
        "logs": d.get("logs", []),
        "updated_at": up.isoformat() if isinstance(up, datetime) else None,
        "age_sec": (int((datetime.now() - up).total_seconds())
                    if isinstance(up, datetime) else None),
    }
