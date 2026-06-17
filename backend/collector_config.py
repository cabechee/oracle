"""수집기(Android 네이티브 앱) 설정 — 어드민(/admin)에서 조정. 수집기가 fetch해 적용.

수집 텀·무엇을 수집할지·마스터 on/off. 수집기는 매 사이클 `GET /collector-config`로
최신값을 받아 그 주기로 동작하므로, 어드민에서 바꾸면 다음 사이클에 반영된다.
설정: settings['collector'].
"""

from typing import Any, Dict

import db

DEFAULTS: Dict[str, Any] = {
    "enabled": True,                # 마스터 — 끄면 수집기가 전송 안 함
    "sync_interval_min": 1,         # 신호(문자·통화·알림) 수집 텀(분)
    "collect_sms": True,
    "collect_calls": True,
    "collect_notifications": True,
    "collect_location": True,       # 위치 수집(GPS/WiFi/BT 체류 감지·방문·도착말걸기)
}

_INT_KEYS = ("sync_interval_min",)
_BOOL_KEYS = ("enabled", "collect_sms", "collect_calls", "collect_notifications",
              "collect_location")


def get_config() -> Dict[str, Any]:
    doc = db.settings().find_one({"_id": "collector"}) or {}
    cfg = dict(DEFAULTS)
    for k, v in doc.items():
        if k in DEFAULTS:
            cfg[k] = v
    return cfg


def set_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        k: v for k, v in (db.settings().find_one({"_id": "collector"}) or {}).items()
        if k != "_id"
    }
    for k, v in (patch or {}).items():
        if k in _BOOL_KEYS:
            out[k] = bool(v)
        elif k in _INT_KEYS:
            try:
                out[k] = max(1, min(1440, int(v)))   # 1분 ~ 24시간
            except (TypeError, ValueError):
                continue
    db.settings().update_one({"_id": "collector"}, {"$set": out}, upsert=True)
    return get_config()
