"""위치 확인(센싱) 정책 — 폰 포그라운드 추적이 '얼마나 자주·어떻게' 위치를 확인할지.

말 걸기(companion_config)와 **분리**: 센싱은 '지금 어디 있나'를 알아내는 일이고,
말 걸기는 그 결과를 받아 '말할까 말까'를 정하는 일이다. 어차피 위치 확인은 동반자
말고도 쓸 수 있으니(일기 방문기록 등) companion 하위가 아니라 독립 도메인으로 둔다.

설정: settings['location'] (어드민 📍 장소). 폰이 fetch해서 포그라운드 서비스에 적용.
"""

from typing import Any, Dict

import db

DEFAULTS: Dict[str, Any] = {
    "poll_interval_sec": 30,        # 위치 확인 주기(초) — 폰 포그라운드 틱 간격(운전 중엔 10초로 자동)
    "skip_on_known_wifi": True,     # 등록된 장소 WiFi에 물려 있으면 GPS 스킵(배터리·실내정확)
    # ── 차량 출차/주차 판정 임계값 (수집기 상태머신) ──
    "car_depart_radius_m": 50,      # 출차: 차 BT 연결 채로 세운 데서 이만큼 벗어나면 운전중
    "car_stationary_radius_m": 75,  # 안전망: 운전중 이 반경 안에 머물면 '정지'로 침
    "car_stationary_reset_min": 120,  # 안전망: 정지 이만큼 지속되면 조용히 주차중 리셋(충전 고려 2h)
    "car_park_debounce_ticks": 2,   # 주차: BT 해제가 연속 이만큼 틱이어야 확정(시동 깜빡임 흡수)
    "car_charge_check_min": 10,     # 운전중 이만큼 정지하면 테슬라로 충전중인지 확인(1회)
    "car_dest_recheck_min": 3,      # 출차 시 목적지 없으면 이만큼 뒤 1회 재확인 후 '어디 가?'
}

# 키별 정수 범위 (의미가 달라 클램프를 분리)
_INT_RANGES = {
    "poll_interval_sec": (15, 3600),        # 15초 ~ 1시간
    "car_depart_radius_m": (20, 5000),
    "car_stationary_radius_m": (20, 1000),
    "car_stationary_reset_min": (5, 480),
    "car_park_debounce_ticks": (1, 10),
    "car_charge_check_min": (1, 120),
    "car_dest_recheck_min": (1, 60),
}
_INT_KEYS = tuple(_INT_RANGES)
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
            lo, hi = _INT_RANGES[k]
            try:
                out[k] = max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                continue
    db.settings().update_one({"_id": "location"}, {"$set": out}, upsert=True)
    return get_config()
