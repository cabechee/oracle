"""장소 레지스트리 + 위치 센싱 설정 라우터 — 폰 캡처 + 어드민 관리 공용."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

import places as places_mod
import location_config as loc_cfg

router = APIRouter()


class PlaceIn(BaseModel):
    name: str
    kind: Optional[str] = None         # home | office | place
    lat: Optional[float] = None
    lng: Optional[float] = None
    wifi: Optional[str] = None         # 단일(하위호환)
    bt: Optional[str] = None
    wifis: Optional[List[str]] = None  # WiFi 여러 개 — 하나라도 잡히면 이 장소(OR)
    bts: Optional[List[str]] = None    # 블루투스 기기 여러 개 — 하나라도 연결되면 이 장소(OR)
    description: Optional[str] = None
    id: Optional[str] = None           # 주면 그 문서 수정(어드민 설명 편집 등)


@router.get("/places")
def ep_list_places():
    """등록된 장소 — 폰 지오펜스 동기화 + 어드민 표시."""
    return {"items": places_mod.list_places()}


@router.post("/places")
def ep_upsert_place(body: PlaceIn):
    """장소 등록/수정 — WiFi 감지·수동 추가(폰) 또는 설명 편집(어드민)."""
    if not body.name.strip():
        raise HTTPException(400, "name 비어있음")
    return places_mod.upsert(
        body.name, kind=body.kind, lat=body.lat, lng=body.lng,
        wifi=body.wifi, bt=body.bt, wifis=body.wifis, bts=body.bts,
        description=body.description, place_id=body.id)


@router.delete("/places/{place_id}")
def ep_delete_place(place_id: str):
    if not places_mod.delete(place_id):
        raise HTTPException(404, "not found")
    return {"ok": True}


# ── 위치 센싱 설정 (말 걸기와 분리 — '어떻게 위치를 확인할지') ──────
@router.get("/location-config")
def ep_get_location_config():
    return {"config": loc_cfg.get_config()}


@router.post("/location-config")
def ep_set_location_config(patch: Dict[str, Any] = Body(...)):
    """위치 확인 설정 부분 갱신 (poll_interval_sec·skip_on_known_wifi)."""
    return {"config": loc_cfg.set_config(patch)}
