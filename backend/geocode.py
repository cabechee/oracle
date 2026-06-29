"""역지오코딩 — 좌표 → 한국 지명(Kakao Local). 방문/동선에 '어떤 곳' 대신 지역명.

방문(visits)·동선(tracks)은 등록 안 된 곳이면 좌표만 남아 일기가 "어떤 곳 ×N"으로
무의미하다. 여기서 좌표를 "서귀포시 성산읍"·건물명 등으로 풀어 narrative를 살린다.

graceful: KAKAO_REST_KEY 없으면 reverse()가 None(기존 동작 유지, 앱 안 깨짐).
같은 자리 반복 호출은 geocache(반올림 좌표 격자)로 절약 — 빈 결과도 캐시(재호출 방지).
"""

from datetime import date, datetime, time as dtime
from typing import Any, Dict, Optional

import httpx

import db
from config import KAKAO_REST_KEY

_KAKAO_URL = "https://dapi.kakao.com/v2/local/geo/coord2address.json"


def _round_key(lat: float, lng: float) -> str:
    """~11m 격자 캐시 키 — 방문 체크포인트 단위론 충분(과한 중복 호출 방지)."""
    return f"{round(float(lat), 4)},{round(float(lng), 4)}"


def _display(doc: Dict[str, Any]) -> Optional[str]:
    """Kakao coord2address 문서 → 사람이 읽는 지명. 건물명 > 시군구+읍면동."""
    ra = doc.get("road_address") or {}
    ad = doc.get("address") or {}
    building = (ra.get("building_name") or "").strip()
    r2 = (ad.get("region_2depth_name") or ra.get("region_2depth_name") or "").strip()  # 시/군/구
    r3 = (ad.get("region_3depth_name") or ra.get("region_3depth_name") or "").strip()  # 읍/면/동
    if building:
        return f"{building} ({r2})" if r2 else building
    name = " ".join(p for p in (r2, r3) if p)
    return name or None


def reverse(lat: Optional[float], lng: Optional[float], use_cache: bool = True) -> Optional[str]:
    """좌표 → 지명. 키 없거나 실패하면 None. 캐시는 실제 호출 결과만 저장(키 없을 땐 캐시 안 함)."""
    if lat is None or lng is None:
        return None
    key = _round_key(lat, lng)
    if use_cache:
        c = db.geocache().find_one({"_id": key})
        if c is not None:
            return c.get("name")            # 캐시 히트(None=주소 없음으로 판명된 것도 그대로)
    if not KAKAO_REST_KEY:
        return None                         # 키 없음 — 캐시에 안 남김(키 생기면 다시 시도되도록)
    try:
        r = httpx.get(
            _KAKAO_URL,
            params={"x": float(lng), "y": float(lat)},   # Kakao는 x=경도, y=위도(WGS84)
            headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"},
            timeout=6.0,
        )
        if r.status_code != 200:
            return None                     # 실패는 캐시 안 함(일시 오류 재시도 여지)
        docs = r.json().get("documents") or []
        name = _display(docs[0]) if docs else None
    except Exception:
        return None
    try:
        db.geocache().update_one(
            {"_id": key},
            {"$set": {"name": name, "lat": float(lat), "lng": float(lng)}},
            upsert=True,
        )
    except Exception:
        pass
    return name


def _fill(query: Dict[str, Any], limit: Optional[int] = None) -> Dict[str, Any]:
    """미등록 방문에 지역명 채움 — 이름 얻었을 때만 area 저장(못 얻으면 다음에 재시도).

    키 없을 땐 통째로 스킵: area=None을 박아두면 나중에 키가 생겨도 '이미 area 있음'으로
    걸러져 영영 지명이 안 붙는다(캐시 독). area는 '이름 붙은 것'만 갖게 한다.
    """
    if not KAKAO_REST_KEY:
        return {"processed": 0, "named": 0, "skipped": "no_key"}
    cur = db.visits().find(query)
    if limit is not None:
        cur = cur.limit(limit)
    done = named = 0
    for v in cur:
        done += 1
        name = reverse(v.get("lat"), v.get("lng"))
        if name:
            db.visits().update_one({"_id": v["_id"]}, {"$set": {"area": name}})
            named += 1
    return {"processed": done, "named": named}


def ensure_day(target: date) -> Dict[str, Any]:
    """그날 방문에 지역명 채움 — 일기 생성 직전 호출(nightly·재생성). place 지정·area 있는 건 제외."""
    t0 = datetime.combine(target, dtime.min)
    t1 = datetime.combine(target, dtime.max)
    return _fill({
        "start": {"$gte": t0, "$lte": t1},
        "area": {"$exists": False},
        "$or": [{"place": None}, {"place": ""}],
    })


def backfill_visits(limit: int = 1000) -> Dict[str, Any]:
    """area 없는 미등록 방문 전체 소급(여행 전 기록 등) — 수동 트리거(/geocode/backfill)."""
    return _fill({"area": {"$exists": False}, "$or": [{"place": None}, {"place": ""}]}, limit)
