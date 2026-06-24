"""Tesla Fleet API — 차량 위치·운행 상태 읽기 (차 상태머신 보강).

인증(OAuth2 authorization_code, 1회): `python scripts/tesla_auth.py` → tesla_token.json 저장
→ refresh_token 자동 갱신. 파트너 등록(공개키 호스팅+도메인)은 scripts/tesla_register.py.

설계 — **Oracle은 테슬라 때문에 죽지 않는다**: 미설정·토큰 없음·네트워크/권한 실패를
전부 graceful(빈 결과 / authed=False). 읽기 전용(vehicle_data). 원격 명령은 차량 명령
프로토콜+개인키 서명이 필요해 후속(개인키는 TESLA_PRIVATE_KEY_PATH에 준비됨).
"""

import json
import time
from typing import Any, Dict, List, Optional

import httpx

import config

_AUTH = "https://auth.tesla.com/oauth2/v3"
_TOKEN_URL = f"{_AUTH}/token"

# client_credentials(파트너) 토큰 캐시 — 파트너 등록·계정 레벨.
_partner: Dict[str, Any] = {"token": None, "exp": 0.0}


def _load_token() -> Optional[Dict[str, Any]]:
    try:
        with open(config.TESLA_TOKEN_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save_token(tok: Dict[str, Any]) -> None:
    try:
        with open(config.TESLA_TOKEN_PATH, "w") as f:
            json.dump(tok, f)
    except Exception:
        pass


def _access_token() -> Optional[str]:
    """유효한 사용자 access token — 만료 임박이면 refresh_token으로 갱신. 없으면 None."""
    tok = _load_token()
    if not tok:
        return None
    if tok.get("access_token") and float(tok.get("expires_at", 0)) - 60 > time.time():
        return tok["access_token"]
    rt = tok.get("refresh_token")
    if not rt or not config.TESLA_CLIENT_ID:
        return None
    try:
        r = httpx.post(_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": config.TESLA_CLIENT_ID,
            "refresh_token": rt,
        }, timeout=30)
        r.raise_for_status()
        new = r.json()
        new["expires_at"] = time.time() + int(new.get("expires_in", 28800))
        new.setdefault("refresh_token", rt)   # 일부 응답은 refresh_token 생략
        _save_token(new)
        return new.get("access_token")
    except Exception as e:
        print(f"[tesla] refresh 실패: {e}", flush=True)
        return None


def partner_token() -> Optional[str]:
    """파트너 토큰(client_credentials) — 파트너 등록용. 캐시. 미설정이면 None."""
    if _partner["token"] and _partner["exp"] - 60 > time.time():
        return _partner["token"]
    if not (config.TESLA_CLIENT_ID and config.TESLA_CLIENT_SECRET):
        return None
    try:
        r = httpx.post(_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": config.TESLA_CLIENT_ID,
            "client_secret": config.TESLA_CLIENT_SECRET,
            "scope": config.TESLA_SCOPES,
            "audience": config.TESLA_API_BASE,
        }, timeout=30)
        r.raise_for_status()
        d = r.json()
        _partner["token"] = d.get("access_token")
        _partner["exp"] = time.time() + int(d.get("expires_in", 28800))
        return _partner["token"]
    except Exception as e:
        print(f"[tesla] partner token 실패: {e}", flush=True)
        return None


def is_authed() -> bool:
    return _access_token() is not None


def _get(path: str) -> Optional[Dict[str, Any]]:
    at = _access_token()
    if not at:
        return None
    try:
        r = httpx.get(f"{config.TESLA_API_BASE}{path}",
                      headers={"Authorization": f"Bearer {at}"}, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[tesla] GET {path} 실패: {e}", flush=True)
        return None


def vehicles() -> List[Dict[str, Any]]:
    """등록 차량 목록. 미인증/실패면 []."""
    d = _get("/api/1/vehicles")
    return (d or {}).get("response") or []


# 전체 스냅샷용 — 공조·주행거리계까지. 운전 폴링은 가벼운 기본(drive/charge)만.
_FULL_ENDPOINTS = ("charge_state;climate_state;drive_state;"
                   "vehicle_state;gui_settings;location_data")


def vehicle_data(vin: str,
                 endpoints: str = "drive_state;charge_state;location_data"
                 ) -> Optional[Dict[str, Any]]:
    """차량 상세. 차가 잠들어 있으면 408 → None(필요 시 wake 후 재시도).

    endpoints 로 섹션 지정 — 기본은 가벼운 위치·충전(운전 폴링), snapshot() 은
    _FULL_ENDPOINTS 로 공조·주행거리계까지.
    ⚠️ 자주 부르면 차를 깨워 배터리 소모 — 이벤트 시점에만 호출 권장.
    """
    d = _get(f"/api/1/vehicles/{vin}/vehicle_data?endpoints={endpoints}")
    return (d or {}).get("response")


def location(vin: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """현재 위치·운행·목적지 요약 — 차 상태머신 보강용(이벤트 시점 호출).

    ⚠️ **자는 차는 안 깨운다**(state!=online이면 None) — wake가 제일 비싸서. 운전 중 차는
    online이라 출차/주차 순간엔 그대로 읽힌다. 내비 켜져 있으면 목적지(dest_*)도 채워짐.
    반환: {vin,lat,lng,shift,speed,driving,dest,dest_lat,dest_lng,eta_min,ts} 또는 None.
    """
    vs = vehicles()
    if not vs:
        return None
    v = next((x for x in vs if x.get("vin") == vin), vs[0]) if vin else vs[0]
    if v.get("state") != "online":
        return None   # asleep/offline — 깨우지 않음(비용·배터리)
    data = vehicle_data(v.get("vin"))
    if not data:
        return None
    ds = data.get("drive_state") or {}
    shift = ds.get("shift_state")
    return {
        "vin": v.get("vin"),
        "lat": ds.get("latitude"),
        "lng": ds.get("longitude"),
        "shift": shift,                       # P | D | R | N | None
        "speed": ds.get("speed"),
        "driving": shift in ("D", "R", "N"),  # P/None = 정차로 본다
        "dest": ds.get("active_route_destination"),       # 내비 목적지(켰을 때)
        "dest_lat": ds.get("active_route_latitude"),
        "dest_lng": ds.get("active_route_longitude"),
        "eta_min": ds.get("active_route_minutes_to_arrival"),
        "ts": ds.get("timestamp"),
    }


def charge(vin: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """충전 상태 — 운전중 정지 시 '충전 중인가' 확인용. 자는 차는 안 깨움(None)."""
    vs = vehicles()
    if not vs:
        return None
    v = next((x for x in vs if x.get("vin") == vin), vs[0]) if vin else vs[0]
    if v.get("state") != "online":
        return None   # asleep/offline — 안 깨움
    data = vehicle_data(v.get("vin"))
    if not data:
        return None
    cs = data.get("charge_state") or {}
    state = cs.get("charging_state")          # Charging | Complete | Disconnected | Stopped | NoPower
    return {
        "vin": v.get("vin"),
        "charging": state == "Charging",
        "state": state,
        "level": cs.get("battery_level"),
        "added_kwh": cs.get("charge_energy_added"),
        "mins_left": cs.get("minutes_to_full_charge"),
    }


def snapshot(vin: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """차 전체 스냅샷 — 배터리·충전·공조·주행거리계·위치를 한 번에 정규화(마일→km).

    수집(car_snapshots)·활용용. 자는 차는 안 깨움(None). 이벤트(출차/주차/충전) 시점 호출.
    location() 호환 필드(lat/lng/shift/dest*/eta)도 포함 — 상태머신이 그대로 쓴다.
    """
    vs = vehicles()
    if not vs:
        return None
    v = next((x for x in vs if x.get("vin") == vin), vs[0]) if vin else vs[0]
    if v.get("state") != "online":
        return None   # asleep/offline — 안 깨움
    data = vehicle_data(v.get("vin"), _FULL_ENDPOINTS)
    if not data:
        return None
    cs = data.get("charge_state") or {}
    cl = data.get("climate_state") or {}
    ds = data.get("drive_state") or {}
    st = data.get("vehicle_state") or {}

    def _km(mi: Any) -> Optional[float]:
        return round(mi * 1.60934, 1) if isinstance(mi, (int, float)) else None

    shift = ds.get("shift_state")
    return {
        "vin": v.get("vin"),
        "ts": ds.get("timestamp") or st.get("timestamp"),
        # 배터리·충전
        "battery": cs.get("battery_level"),
        "battery_range_km": _km(cs.get("battery_range")),
        "charging": cs.get("charging_state") == "Charging",
        "charge_state": cs.get("charging_state"),
        "charge_limit": cs.get("charge_limit_soc"),
        "charge_added_kwh": cs.get("charge_energy_added"),
        "minutes_to_full": cs.get("minutes_to_full_charge"),
        "charger_power_kw": cs.get("charger_power"),
        # 공조·온도
        "inside_temp": cl.get("inside_temp"),
        "outside_temp": cl.get("outside_temp"),
        "climate_on": cl.get("is_climate_on"),
        "temp_setting": cl.get("driver_temp_setting"),
        "preconditioning": cl.get("is_preconditioning"),
        # 위치·운행 (location() 호환 — 상태머신이 쓰는 필드)
        "lat": ds.get("latitude"),
        "lng": ds.get("longitude"),
        "shift": shift,
        "speed": ds.get("speed"),
        "driving": shift in ("D", "R", "N"),
        "dest": ds.get("active_route_destination"),
        "dest_lat": ds.get("active_route_latitude"),
        "dest_lng": ds.get("active_route_longitude"),
        "eta_min": ds.get("active_route_minutes_to_arrival"),
        # 차 상태
        "odometer_km": _km(st.get("odometer")),
        "locked": st.get("locked"),
        "sentry": st.get("sentry_mode"),
        "user_present": st.get("is_user_present"),
        "software": st.get("car_version"),
    }


def wake(vin: str) -> bool:
    """차 깨우기(잠든 차 vehicle_data 전에). 성공 추정 시 True."""
    at = _access_token()
    if not at:
        return False
    try:
        r = httpx.post(f"{config.TESLA_API_BASE}/api/1/vehicles/{vin}/wake_up",
                       headers={"Authorization": f"Bearer {at}"}, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def status() -> Dict[str, Any]:
    """어드민 표시 — 인증 상태 + 차량 요약."""
    if not is_authed():
        return {"authed": False, "has_client": bool(config.TESLA_CLIENT_ID),
                "domain": config.TESLA_DOMAIN}
    vs = vehicles()
    return {
        "authed": True, "has_client": True, "domain": config.TESLA_DOMAIN,
        "vehicles": [{"vin": v.get("vin"), "name": v.get("display_name"),
                      "state": v.get("state")} for v in vs],
    }
