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


def _as_list(p: Dict[str, Any], plural: str, single: str) -> List[str]:
    """다중 필드(wifis/bts) 우선, 없으면 구 단일 필드(wifi/bt)를 1-원소 리스트로 마이그레이션."""
    v = p.get(plural)
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = p.get(single)
    return [str(s).strip()] if s and str(s).strip() else []


def _view(p: Dict[str, Any]) -> Dict[str, Any]:
    wifis = _as_list(p, "wifis", "wifi")
    bts = _as_list(p, "bts", "bt")
    return {
        "id": p["_id"],
        "name": p.get("name", ""),
        "kind": p.get("kind", "place"),
        "lat": p.get("lat"),
        "lng": p.get("lng"),
        "wifis": wifis,               # WiFi 여러 개 — 하나라도 잡히면 이 장소(OR)
        "bts": bts,                   # 블루투스 기기 여러 개(차 등) — 하나라도 연결되면 이 장소(OR)
        "wifi": wifis[0] if wifis else None,   # 하위호환(구 단일)
        "bt": bts[0] if bts else None,
        "description": p.get("description", ""),
    }


def upsert(name: Optional[str] = None, kind: Optional[str] = None,
           lat: Optional[float] = None, lng: Optional[float] = None,
           wifi: Optional[str] = None, description: Optional[str] = None,
           bt: Optional[str] = None, place_id: Optional[str] = None,
           wifis: Optional[List[str]] = None,
           bts: Optional[List[str]] = None) -> Dict[str, Any]:
    """장소 등록/수정 — 명시한 필드만 바꾸고 나머진 보존(설명만 편집 등).

    WiFi·BT는 **여러 개**(wifis/bts 리스트) 등록 가능 — 하나라도 잡히면 그 장소(OR 매칭).
    단일 wifi/bt도 받음(1-원소 리스트로). place_id 주면 그 문서 갱신, 아니면 멱등 id.
    """
    now = datetime.now()
    eff_kind = kind if kind in KINDS else None
    rep_wifi = (wifis[0].strip() if wifis else "") or (wifi or "").strip() or None
    rep_bt = (bts[0].strip() if bts else "") or (bt or "").strip() or None
    pid = place_id or _pid((name or "").strip() or "이름 없는 곳",
                           eff_kind or "place", rep_wifi, lat, lng, rep_bt)
    existing = db.places().find_one({"_id": pid})
    doc: Dict[str, Any] = dict(existing) if existing else {
        "_id": pid, "created": now, "name": "이름 없는 곳",
        "kind": "place", "description": "",
    }
    # 기존 구 단일 필드 → 리스트로 일원화(부분 수정 시 유실 방지)
    if "wifis" not in doc:
        doc["wifis"] = _as_list(doc, "wifis", "wifi")
    if "bts" not in doc:
        doc["bts"] = _as_list(doc, "bts", "bt")
    doc.pop("wifi", None)
    doc.pop("bt", None)
    if name is not None and name.strip():
        doc["name"] = name.strip()
    if eff_kind:
        doc["kind"] = eff_kind
    if wifis is not None:
        doc["wifis"] = [w.strip() for w in wifis if w and w.strip()]
    elif wifi is not None:
        doc["wifis"] = [wifi.strip()] if wifi.strip() else []
    if bts is not None:
        doc["bts"] = [b.strip() for b in bts if b and b.strip()]
    elif bt is not None:
        doc["bts"] = [bt.strip()] if bt.strip() else []
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
