"""장소 레지스트리 — 집·작업실·자주 가는 곳. 이름·좌표·WiFi·설명.

폰이 WiFi 감지(붙은 SSID가 미등록이면 "여기 저장할까?")나 수동 추가로 등록하고,
지오펜스 판정은 폰 로컬 사본으로 즉시 한다(오프라인·배터리). 백엔드는 SoT이자
동반자 맥락(설명)의 출처 — 도착 멘트가 "여기 작업실이지? 작업 잘 돼요?"처럼 알게.
어드민(/admin)에서 보고 설명을 고친다.
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import db

KINDS = ("home", "office", "place")

# 집·작업실 표시명 — 동반자 맥락/어드민에서 쓰는 한글 라벨
KIND_LABEL = {"home": "집", "office": "작업실", "place": "장소"}


def _pid(name: str, kind: str, wifi: Optional[str], lat: Optional[float],
         lng: Optional[float], bt: Optional[str] = None) -> str:
    """안정적 id — 집·작업실은 하나씩(갱신), 그 외는 이름+(BT/WiFi/좌표) 해시(멱등).

    차처럼 좌표 없이 BT로만 식별되는 장소도 BT 키로 안정적 id를 갖는다.
    """
    if kind in ("home", "office"):
        return f"place-{kind}"
    if bt:
        base = "bt:" + bt.strip().lower()
    elif wifi:
        base = wifi.strip().lower()
    elif lat is not None and lng is not None:
        base = f"{round(float(lat), 4)},{round(float(lng), 4)}"
    else:
        base = name
    return "place-" + hashlib.sha1(f"{name}|{base}".encode()).hexdigest()[:10]


def _view(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["_id"],
        "name": p.get("name", ""),
        "kind": p.get("kind", "place"),
        "lat": p.get("lat"),
        "lng": p.get("lng"),
        "wifi": p.get("wifi"),
        "bt": p.get("bt"),            # 블루투스 기기명(차 등) — 연결되면 그 장소로
        "description": p.get("description", ""),
    }


def upsert(name: Optional[str] = None, kind: Optional[str] = None,
           lat: Optional[float] = None, lng: Optional[float] = None,
           wifi: Optional[str] = None, description: Optional[str] = None,
           bt: Optional[str] = None,
           place_id: Optional[str] = None) -> Dict[str, Any]:
    """장소 등록/수정 — 명시한 필드만 바꾸고 나머진 보존(설명만 편집 등).

    place_id 주면 그 문서 갱신, 아니면 이름+kind+(BT/WiFi/좌표)로 멱등 id. 집·작업실은 하나씩.
    """
    now = datetime.now()
    eff_kind = kind if kind in KINDS else None
    pid = place_id or _pid((name or "").strip() or "이름 없는 곳",
                           eff_kind or "place", (wifi or "").strip() or None,
                           lat, lng, (bt or "").strip() or None)
    existing = db.places().find_one({"_id": pid})
    doc: Dict[str, Any] = dict(existing) if existing else {
        "_id": pid, "created": now, "name": "이름 없는 곳",
        "kind": "place", "wifi": None, "bt": None, "description": "",
    }
    if name is not None and name.strip():
        doc["name"] = name.strip()
    if eff_kind:
        doc["kind"] = eff_kind
    if wifi is not None:
        doc["wifi"] = wifi.strip() or None
    if bt is not None:
        doc["bt"] = bt.strip() or None
    if description is not None:
        doc["description"] = description.strip()
    if lat is not None:
        doc["lat"] = float(lat)
    if lng is not None:
        doc["lng"] = float(lng)
    doc["updated"] = now
    db.places().replace_one({"_id": pid}, doc, upsert=True)
    return _view(doc)


def get(place_id: str) -> Optional[Dict[str, Any]]:
    p = db.places().find_one({"_id": place_id})
    return _view(p) if p else None


def list_places() -> List[Dict[str, Any]]:
    """집·작업실 먼저, 그다음 이름순."""
    order = {"home": 0, "office": 1, "place": 2}
    items = [_view(p) for p in db.places().find()]
    items.sort(key=lambda x: (order.get(x["kind"], 9), x["name"]))
    return items


def delete(place_id: str) -> bool:
    return db.places().delete_one({"_id": place_id}).deleted_count > 0


def lookup(name_or_kind: Optional[str]) -> Optional[Dict[str, Any]]:
    """이름 또는 kind('home'·'office')로 장소 1건 (동반자 도착/나섬 멘트 맥락). 없으면 None."""
    if not name_or_kind:
        return None
    key = name_or_kind.strip()
    p = db.places().find_one({"kind": key}) if key in KINDS else None
    if not p:
        p = db.places().find_one({"name": key})
    return _view(p) if p else None


def describe(name_or_kind: Optional[str]) -> str:
    """동반자 맥락용 — place 이름/kind로 그곳 설명을 찾는다. 없으면 ''."""
    p = lookup(name_or_kind)
    return (p["description"] or "").strip() if p else ""
