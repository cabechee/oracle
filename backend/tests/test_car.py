"""차량 출차/주차 — 운행 스레드(어디 가?→잘 도착했어?)·안전망 silent·게이팅·임계값."""

from datetime import datetime, timedelta

import pytest

import companion_config as cc
import location_config as lc
from agent import companion


@pytest.fixture(autouse=True)
def _default_no_tesla(monkeypatch):
    """기본: 테슬라 비활성 + 장소매칭 None — 테스트가 실 API/Mongo를 안 때리게.
    (보강 테스트는 각자 override)."""
    monkeypatch.setattr(companion, "_tesla_at_event", lambda: None)
    monkeypatch.setattr(companion.places_mod, "nearest", lambda *a, **k: None)
    monkeypatch.setattr(companion.db, "conversations", lambda: _FakeConvos())  # 흐름 저장 흡수


class _FakeSettings:
    def __init__(self, docs=None):
        self.docs = {d["_id"]: dict(d) for d in (docs or [])}

    def find_one(self, flt):
        d = self.docs.get(flt.get("_id"))
        return dict(d) if d else None

    def update_one(self, flt, update, upsert=False):
        doc = self.docs.setdefault(flt["_id"], {"_id": flt["_id"]})
        doc.update(update.get("$set", {}))


class _FakeConvos:
    """role + ts>$gt 필터 + ts 오름차순 첫 건 (pymongo find_one(sort=) 흉내)."""
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, flt, sort=None):
        after = (flt.get("ts") or {}).get("$gt")
        role = flt.get("role")
        cand = [d for d in self.docs
                if d.get("role") == role and (after is None or d["ts"] > after)]
        cand.sort(key=lambda d: d["ts"])
        return dict(cand[0]) if cand else None

    def insert_one(self, doc):
        self.docs.append(doc)


def _capture_speak(monkeypatch):
    """_speak를 가짜로 — 호출된 (kind, situation) 캡처하고 고정 텍스트 반환."""
    calls = []

    def fake(kind, situation, speaker=None):
        calls.append({"kind": kind, "situation": situation, "speaker": speaker})
        return {"speaker": "베르", "text": "응 거기 어때?", "alias": "x"}

    monkeypatch.setattr(companion, "_speak", fake)
    return calls


# ── 출차: 운행 스레드 시작 ──
def test_departure_no_dest_defers(monkeypatch):
    # 목적지 없으면 즉답 보류({recheck:true}) — 운행 시작만 기록, 멘트 X.
    s = _FakeSettings()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    calls = _capture_speak(monkeypatch)
    r = companion.car_departure(37.5, 127.0, 1718000000000)  # autouse _tesla_at_event=None → 목적지 없음
    assert r.get("recheck") is True and r["text"] == ""
    assert calls == []                                  # 멘트 안 함(보류)
    drive = s.docs["drive"]
    assert drive["state"] == "driving" and "question_ts" not in drive


def test_departure_recheck_asks(monkeypatch):
    # 3분 재확인에도 목적지 없으면 '어디 가?' 멘트 + 흐름 저장.
    s = _FakeSettings([{"_id": "drive", "state": "driving",
                        "departed_at": datetime(2026, 6, 20, 10, 0)}])
    cv = _FakeConvos()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion.db, "conversations", lambda: cv)
    calls = _capture_speak(monkeypatch)
    r = companion.car_departure(37.5, 127.0, recheck=True)
    assert r["text"] == "응 거기 어때?" and "어디 가" in calls[0]["situation"]
    assert isinstance(s.docs["drive"]["question_ts"], datetime)
    assert len(cv.docs) == 1                             # 흐름 자동 저장


def test_departure_gated_no_question_ts(monkeypatch):
    s = _FakeSettings()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion, "_speak",
                        lambda *a, **k: {"speaker": "", "text": "", "alias": ""})
    companion.car_departure(37.5, 127.0)
    drive = s.docs["drive"]
    assert drive["state"] == "driving"
    assert "question_ts" not in drive    # 억제됐으면 매칭 기준 없음(주차 때 generic)


# ── 주차: 답 매칭 / generic / silent ──
def test_parking_links_destination(monkeypatch):
    qts = datetime(2026, 6, 19, 14, 0)
    s = _FakeSettings([{"_id": "drive", "state": "driving", "question_ts": qts}])
    convos = _FakeConvos([
        {"role": "user", "text": "강남 가", "ts": qts + timedelta(minutes=1)},
        {"role": "user", "text": "딴소리", "ts": qts + timedelta(minutes=5)},
    ])
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion.db, "conversations", lambda: convos)
    import parking
    recorded = []
    monkeypatch.setattr(parking, "record",
                        lambda lat, lng, ts=None: recorded.append((lat, lng)))
    calls = _capture_speak(monkeypatch)
    companion.car_parking(37.49, 127.03, 1718000300000)
    assert recorded == [(37.49, 127.03)]              # 위치는 항상 기록
    assert "강남" in calls[0]["situation"]            # 출발 첫 답을 목적지로
    assert "잘 도착" in calls[0]["situation"]
    assert s.docs["drive"]["state"] == "parked"       # 운행 닫힘
    assert s.docs["drive"]["question_ts"] is None


def test_parking_no_answer_generic(monkeypatch):
    s = _FakeSettings([{"_id": "drive", "state": "driving"}])   # question_ts 없음
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion.db, "conversations", lambda: _FakeConvos())
    import parking
    monkeypatch.setattr(parking, "record", lambda *a, **k: None)
    calls = _capture_speak(monkeypatch)
    companion.car_parking(37.49, 127.03)
    assert "잘 도착" not in calls[0]["situation"]       # 답 없으면 도착 확인 안 함
    assert "세웠" in calls[0]["situation"]


def test_parking_silent_no_question(monkeypatch):
    s = _FakeSettings([{"_id": "drive", "state": "driving"}])
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    import parking
    recorded = []
    monkeypatch.setattr(parking, "record",
                        lambda lat, lng, ts=None: recorded.append((lat, lng)))
    monkeypatch.setattr(companion, "_speak",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("silent엔 말 X")))
    r = companion.car_parking(37.49, 127.03, silent=True)
    assert r["text"] == ""
    assert recorded == [(37.49, 127.03)]              # 위치는 남김(내 차 어디)
    assert s.docs["drive"]["state"] == "parked"


# ── 테슬라 보강(Phase 1): 목적지·정밀위치·장소매칭 ──
def test_departure_tesla_destination(monkeypatch):
    s = _FakeSettings()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    # 테슬라가 내비 목적지 좌표를 줌 → places가 '회사'로 매칭
    monkeypatch.setattr(companion, "_tesla_at_event",
                        lambda: {"lat": 37.5, "lng": 127.0, "driving": True,
                                 "dest_lat": 37.49, "dest_lng": 127.03, "dest": "Gangnam"})
    monkeypatch.setattr(companion.places_mod, "nearest",
                        lambda lat, lng, r=150: {"name": "회사"})
    calls = _capture_speak(monkeypatch)
    companion.car_departure(37.5, 127.0)
    assert "회사" in calls[0]["situation"] and "가는구나" in calls[0]["situation"]
    assert s.docs["drive"]["destination"] == "회사"   # 주차 매칭용 저장


def test_parking_tesla_here_and_precise(monkeypatch):
    s = _FakeSettings([{"_id": "drive", "state": "driving"}])
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    # 테슬라 정밀 좌표 + 도착지 '집' 매칭
    monkeypatch.setattr(companion, "_tesla_at_event",
                        lambda: {"lat": 37.493, "lng": 127.031})
    monkeypatch.setattr(companion.places_mod, "nearest",
                        lambda lat, lng, r=150: {"name": "집"})
    import parking
    recorded = []
    monkeypatch.setattr(parking, "record",
                        lambda lat, lng, ts=None: recorded.append((lat, lng)))
    calls = _capture_speak(monkeypatch)
    companion.car_parking(99.9, 99.9)                 # 폰 좌표 엉뚱해도 테슬라 우선
    assert recorded == [(37.493, 127.031)]            # 테슬라 정밀 좌표로 기록
    assert "집" in calls[0]["situation"]


# ── 흐름(conversations) 자동 저장: 탭 안 해도 차 멘트가 흐름에 남아야 ──
def test_departure_dest_logs_to_flow(monkeypatch):
    # 목적지(회사) 있으면 즉답 '회사 가는구나' + 흐름 자동 저장(trigger='회사로 출발').
    s = _FakeSettings()
    cv = _FakeConvos()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion.db, "conversations", lambda: cv)
    monkeypatch.setattr(companion, "_tesla_at_event",
                        lambda: {"dest_lat": 37.49, "dest_lng": 127.03, "dest": "X"})
    monkeypatch.setattr(companion.places_mod, "nearest", lambda *a, **k: {"name": "회사"})
    _capture_speak(monkeypatch)
    companion.car_departure(37.5, 127.0)
    assert len(cv.docs) == 1
    assert cv.docs[0]["companion"] is True and cv.docs[0]["role"] == "assistant"
    assert cv.docs[0]["text"] == "응 거기 어때?" and cv.docs[0].get("trigger") == "회사로 출발"


def test_charging_check(monkeypatch):
    # 충전 중이면 '충전 중' 멘트 + 흐름; 아니면 침묵.
    cv = _FakeConvos()
    monkeypatch.setattr(companion.db, "settings", lambda: _FakeSettings())
    monkeypatch.setattr(companion.db, "conversations", lambda: cv)
    import tesla
    monkeypatch.setattr(tesla, "is_authed", lambda: True)
    monkeypatch.setattr(companion, "_tesla_budget_ok", lambda: True)
    monkeypatch.setattr(tesla, "charge", lambda vin=None: {"charging": True, "state": "Charging", "level": 62})
    _capture_speak(monkeypatch)
    r = companion.car_charging_check(37.49, 127.03)
    assert r["charging"] is True and r["text"] == "응 거기 어때?"
    assert len(cv.docs) == 1 and cv.docs[0]["trigger"] == "충전 중"
    # 충전 아님 → 침묵
    monkeypatch.setattr(tesla, "charge", lambda vin=None: {"charging": False, "state": "Disconnected"})
    cv.docs.clear()
    r2 = companion.car_charging_check(37.49, 127.03)
    assert r2["charging"] is False and r2["text"] == "" and cv.docs == []


def test_parking_logs_to_flow(monkeypatch):
    s = _FakeSettings([{"_id": "drive", "state": "driving"}])
    cv = _FakeConvos()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion.db, "conversations", lambda: cv)
    import parking
    monkeypatch.setattr(parking, "record", lambda *a, **k: None)
    _capture_speak(monkeypatch)
    companion.car_parking(37.49, 127.03)
    assert len(cv.docs) == 1 and cv.docs[0]["text"] == "응 거기 어때?"
    assert cv.docs[0]["companion"] is True


def test_parking_silent_no_flow_log(monkeypatch):
    s = _FakeSettings([{"_id": "drive", "state": "driving"}])
    cv = _FakeConvos()
    monkeypatch.setattr(companion.db, "settings", lambda: s)
    monkeypatch.setattr(companion.db, "conversations", lambda: cv)
    import parking
    monkeypatch.setattr(parking, "record", lambda *a, **k: None)
    companion.car_parking(37.49, 127.03, silent=True)
    assert cv.docs == []          # 안전망 침묵 → 흐름에도 안 남김


def test_first_user_reply_after(monkeypatch):
    base = datetime(2026, 6, 19, 14, 0)
    convos = _FakeConvos([
        {"role": "assistant", "text": "어디 가?", "ts": base},
        {"role": "user", "text": "병원", "ts": base + timedelta(minutes=2)},
        {"role": "user", "text": "두번째", "ts": base + timedelta(minutes=9)},
    ])
    monkeypatch.setattr(companion.db, "conversations", lambda: convos)
    assert companion._first_user_reply_after(base) == "병원"            # 첫 user 답
    assert companion._first_user_reply_after(base + timedelta(minutes=5)) == "두번째"


# ── companion_config: car 게이팅 ──
def _cc_use(monkeypatch, docs=None):
    fake = _FakeSettings(docs)
    monkeypatch.setattr(cc.db, "settings", lambda: fake)
    return fake


def test_car_gating_quiet_vs_day(monkeypatch):
    _cc_use(monkeypatch)   # 기본 quiet 23~8, car_cooldown 3
    assert cc.should_speak("car", datetime(2026, 6, 19, 2, 0)) is False   # 새벽 침묵
    assert cc.should_speak("car", datetime(2026, 6, 19, 14, 0)) is True   # 낮 OK


def test_car_disabled(monkeypatch):
    _cc_use(monkeypatch, [{"_id": "companion", "car_enabled": False}])
    assert cc.should_speak("car", datetime(2026, 6, 19, 14, 0)) is False


def test_car_cooldown(monkeypatch):
    now = datetime(2026, 6, 19, 14, 0)
    s = _cc_use(monkeypatch,
                [{"_id": "companion_state", "last_car": now - timedelta(minutes=1)}])
    assert cc.should_speak("car", now) is False        # 1분 전 → 쿨다운(3분) 미충족
    s.docs["companion_state"]["last_car"] = now - timedelta(minutes=5)
    assert cc.should_speak("car", now) is True


def test_car_mark_spoken(monkeypatch):
    s = _cc_use(monkeypatch)
    now = datetime(2026, 6, 19, 14, 0)
    cc.mark_spoken("car", now)
    assert s.docs["companion_state"]["last_car"] == now


# ── location_config: 차량 임계값 ──
def test_car_thresholds_defaults(monkeypatch):
    monkeypatch.setattr(lc.db, "settings", lambda: _FakeSettings())
    cfg = lc.get_config()
    assert cfg["car_depart_radius_m"] == 50
    assert cfg["car_stationary_reset_min"] == 120
    assert cfg["car_charge_check_min"] == 10
    assert cfg["car_dest_recheck_min"] == 3
    assert cfg["car_park_debounce_ticks"] == 2


def test_car_thresholds_clamp(monkeypatch):
    s = _FakeSettings()
    monkeypatch.setattr(lc.db, "settings", lambda: s)   # set→get 같은 인스턴스
    out = lc.set_config({"car_depart_radius_m": 999999, "car_park_debounce_ticks": 0,
                         "car_stationary_reset_min": 2})
    assert out["car_depart_radius_m"] == 5000     # hi clamp
    assert out["car_park_debounce_ticks"] == 1    # lo clamp
    assert out["car_stationary_reset_min"] == 5   # lo clamp
