"""위치·시간 이벤트 → 쿠키/베르 한마디 (폰 알림용)."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class SayIn(BaseModel):
    event: str                      # arrive_home | arrive_office | leave_* | deviate | checkin
    place: Optional[str] = None     # 장소명(선택) — 프롬프트 맥락
    speaker: Optional[str] = None   # cookie | berr (미지정=랜덤)


@router.post("/companion/say")
def ep_companion_say(body: SayIn):
    from agent import companion
    return companion.say(body.event, body.place, body.speaker)


class AskPlaceIn(BaseModel):
    lat: float
    lng: float


@router.post("/companion/askplace")
def ep_askplace(body: AskPlaceIn):
    """새 곳 15분+ 체류 — '여기 어디?' 물어봄 + 좌표 보관(답하면 임시 장소로 저장)."""
    import db
    from datetime import datetime
    db.settings().update_one(
        {"_id": "pending_place"},
        {"$set": {"lat": body.lat, "lng": body.lng, "ts": datetime.now()}},
        upsert=True)
    from agent import companion
    return companion.say("askplace")


class BanterIn(BaseModel):
    event: str                      # arrive | leave | board
    place: Optional[str] = None     # 장소명(선택) — 도착이면 그곳 주인이 맞이
    minutes: Optional[int] = None   # 그곳에 머문 시간(선택, 맥락)


@router.post("/companion/banter")
def ep_companion_banter(body: BanterIn):
    """아빠 움직임에 베르·쿠키가 흐름에 자기들끼리 도란도란 — 각 턴은 흐름에 저장.

    반환 notify: 도착(인사)이면 {speaker,text}(폰이 알림 표시), 이동/추측이면 빈 값(흐름에만).
    """
    from agent import companion
    return companion.banter(body.event, body.place, body.minutes)


class CarDepartIn(BaseModel):
    lat: float
    lng: float
    ts: Optional[int] = None         # epoch ms (출발 순간)
    speaker: Optional[str] = None
    recheck: bool = False            # 3분 뒤 목적지 재확인 호출이면 True (수집기가 보냄)


@router.post("/car/departure")
def ep_car_departure(body: CarDepartIn):
    """출차(주차중→운전중) — 목적지 있으면 '회사 가는구나', 없으면 즉답 보류({recheck:true}).

    상태전이 판정(BT 연결+이동)은 수집기가 끝내고 이 순간에만 부른다. recheck=True면 3분 뒤
    재확인(그때도 목적지 없으면 '어디 가?').
    """
    from agent import companion
    return companion.car_departure(body.lat, body.lng, body.ts, body.speaker, body.recheck)


class CarChargeIn(BaseModel):
    lat: float
    lng: float
    speaker: Optional[str] = None


@router.post("/car/charging")
def ep_car_charging(body: CarChargeIn):
    """운전중 오래 정지 — 테슬라로 충전 중인지 확인. 충전이면 '충전 중이네' 반환(아니면 빈 text)."""
    from agent import companion
    return companion.car_charging_check(body.lat, body.lng, body.speaker)


class CarParkIn(BaseModel):
    lat: float
    lng: float
    ts: Optional[int] = None         # epoch ms (주차 순간)
    silent: bool = False             # 안전망(오래 정지해 조용히 리셋)이면 위치만 남기고 침묵
    speaker: Optional[str] = None


@router.post("/car/parking")
def ep_car_parking(body: CarParkIn):
    """주차(운전중→주차중) — 주차 위치 기록 + 질문('어디?'/답했으면 '잘 도착했어?').

    상태전이 판정(BT 해제·디바운스)은 수집기가, 답 매칭·질문은 백엔드가.
    """
    from agent import companion
    return companion.car_parking(body.lat, body.lng, body.ts, body.silent, body.speaker)


@router.get("/car/location")
def ep_car_location():
    """차 현재 GPS — 운전 중 수집기가 메인 위치로 사용(폰 GPS보다 정확).

    자는 차는 안 깨우고 None(tesla.location이 online 아니면 None) — 운전 중만 좌표가 온다.
    """
    import tesla
    loc = tesla.location()
    if not loc or loc.get("lat") is None or loc.get("lng") is None:
        return {"lat": None, "lng": None}
    return {"lat": loc["lat"], "lng": loc["lng"], "driving": bool(loc.get("driving"))}


class AskedIn(BaseModel):
    speaker: str = ""               # 베르 | 쿠키 (표시명)
    text: str                       # 동반자가 먼저 건 멘트
    ts: Optional[int] = None        # epoch ms — 아빠가 알림 탭해 들어온 순간


@router.post("/companion/asked")
def ep_companion_asked(body: AskedIn):
    """동반자 선제 멘트를 흐름에 남긴다 — 아빠가 그 멘트에 '기록'으로 답할 때.

    흐름에서 답한 기록 바로 위에, 탭해 들어온 시각으로 얹힌다.
    """
    if not body.text.strip():
        raise HTTPException(400, "text 비어있음")
    from agent import companion
    return companion.record_asked(body.speaker, body.text, body.ts)
