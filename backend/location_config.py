"""위치 확인(센싱) 정책 — 폰 포그라운드 추적이 '얼마나 자주·어떻게' 위치를 확인할지.

말 걸기(companion_config)와 **분리**: 센싱은 '지금 어디 있나'를 알아내는 일이고,
말 걸기는 그 결과를 받아 '말할까 말까'를 정하는 일이다. 어차피 위치 확인은 동반자
말고도 쓸 수 있으니(일기 방문기록 등) companion 하위가 아니라 독립 도메인으로 둔다.

설정: settings['location'] (어드민 📍 장소). 폰이 fetch해서 포그라운드 서비스에 적용.
"""

from typing import Any, Dict

import db

DEFAULTS: Dict[str, Any] = {
    "poll_interval_sec": 60,        # 위치 확인 주기(초) — 폰 포그라운드 틱 간격
    "skip_on_known_wifi": True,     # 등록된 장소 WiFi에 물려 있으면 GPS 스킵(배터리·실내정확)
}

_INT_KEYS = ("poll_interval_sec",)
_BOOL_KEYS = ("skip_on_known_wifi",)


def get_config() -> Dict[str, Any]:
    doc = db.settings().find_one({"_id": "location"}) or {}
    cfg = dict(DEFAULTS)
    for k, v in doc.items():
        if k in DEFAULTS:
            cfg[k] = v
    return cfg


def set_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        k: v for k, v in (db.settings().find_one({"_id": "location"}) or {}).items()
        if k != "_id"
    }
    for k, v in (patch or {}).items():
        if k in _BOOL_KEYS:
            out[k] = bool(v)
        elif k in _INT_KEYS:
            try:
                out[k] = max(15, min(3600, int(v)))   # 15초 ~ 1시간
            except (TypeError, ValueError):
                continue
    db.settings().update_one({"_id": "location"}, {"$set": out}, upsert=True)
    return get_config()
