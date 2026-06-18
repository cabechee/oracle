"""companion_config — 말 걸기 게이팅(텀·조용구간·시간대·이벤트). DB는 페이크."""

from datetime import datetime, timedelta

import companion_config as cc


class _FakeSettings:
    def __init__(self, docs=None):
        self.docs = {d["_id"]: dict(d) for d in (docs or [])}

    def find_one(self, flt):
        d = self.docs.get(flt.get("_id"))
        return dict(d) if d else None

    def update_one(self, flt, update, upsert=False):
        _id = flt.get("_id")
        doc = self.docs.setdefault(_id, {"_id": _id})
        doc.update(update.get("$set", {}))


def _use(monkeypatch, docs=None):
    fake = _FakeSettings(docs)
    monkeypatch.setattr(cc.db, "settings", lambda: fake)
    return fake


def test_in_window_normal_and_wrap():
    assert cc._in_window(10, 9, 22) is True
    assert cc._in_window(22, 9, 22) is False     # end 배타
    assert cc._in_window(8, 9, 22) is False
    # 밤샘 wrap (23~8)
    assert cc._in_window(2, 23, 8) is True
    assert cc._in_window(23, 23, 8) is True
    assert cc._in_window(8, 23, 8) is False
    assert cc._in_window(12, 23, 8) is False
    assert cc._in_window(5, 9, 9) is False        # 빈 구간(start==end)


def test_kind_of():
    assert cc.kind_of("checkin") == "checkin"
    assert cc.kind_of("arrive_place") == "location"
    assert cc.kind_of("leave_place") == "location"
    assert cc.kind_of("arrive_home") == "location"   # 레거시 매핑
    assert cc.kind_of("leave_visit") == "location"    # 레거시 매핑


def test_master_off_blocks_all(monkeypatch):
    _use(monkeypatch, [{"_id": "companion", "enabled": False}])
    now = datetime(2026, 6, 16, 10, 0)
    assert cc.should_speak("checkin", now) is False
    assert cc.should_speak("location", now) is False


def test_quiet_blocks_all(monkeypatch):
    _use(monkeypatch)  # 디폴트 quiet 23~8
    night = datetime(2026, 6, 16, 2, 0)
    assert cc.should_speak("checkin", night) is False
    assert cc.should_speak("location", night) is False


def test_checkin_active_window(monkeypatch):
    _use(monkeypatch)  # active 9~22, interval 90, last 없음
    assert cc.should_speak("checkin", datetime(2026, 6, 16, 10, 0)) is True
    assert cc.should_speak("checkin", datetime(2026, 6, 16, 8, 30)) is False   # 시작 전
    assert cc.should_speak("checkin", datetime(2026, 6, 16, 22, 30)) is False  # 끝 후


def test_checkin_hourly(monkeypatch):
    # 정각(0~4분)에만 + 시마다 1회.
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_checkin": datetime(2026, 6, 16, 11, 1)}])
    assert cc.should_speak("checkin", datetime(2026, 6, 16, 12, 1)) is True   # 새 시 정각
    # 이미 이 시(12시)에 보냄 → 억제
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_checkin": datetime(2026, 6, 16, 12, 1)}])
    assert cc.should_speak("checkin", datetime(2026, 6, 16, 12, 3)) is False
    # 정각 지남(12:30) → 억제(정각 아님)
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_checkin": datetime(2026, 6, 16, 11, 1)}])
    assert cc.should_speak("checkin", datetime(2026, 6, 16, 12, 30)) is False


def test_park_always_and_declusters(monkeypatch):
    now = datetime(2026, 6, 16, 14, 0)
    # 주차는 'park' 종류 — 최근 도착(last_location)과 무관하게 발화(위치 쿨다운 무시).
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_location": now - timedelta(minutes=1)}])
    assert cc.kind_of("park") == "park"
    assert cc.should_speak("park", now) is True
    # mark_spoken(park) → last_park + last_location 갱신 → 직후 '도착'은 억제(디클러스터),
    # 주차 자체도 2분 자체 쿨다운.
    cc.mark_spoken("park", now)
    assert cc.should_speak("location", now) is False
    assert cc.should_speak("park", now) is False


def test_banter_cooldown_quiet_and_master(monkeypatch):
    now = datetime(2026, 6, 16, 14, 0)
    # 막 떠들었으면(5분 쿨다운) 억제, 충분히 지나면 OK.
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_banter": now - timedelta(minutes=3)}])
    assert cc.should_speak("banter", now) is False
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_banter": now - timedelta(minutes=6)}])
    assert cc.should_speak("banter", now) is True
    # 새벽 조용 구간엔 수다도 침묵.
    assert cc.should_speak("banter", datetime(2026, 6, 16, 2, 0)) is False
    # 위치 마스터(location_enabled) 끄면 수다도 꺼짐.
    _use(monkeypatch, [{"_id": "companion", "location_enabled": False}])
    assert cc.should_speak("banter", now) is False


def test_location_cooldown(monkeypatch):
    now = datetime(2026, 6, 16, 12, 0)
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_location": now - timedelta(minutes=10)}])
    assert cc.should_speak("location", now) is False  # 10 < 30
    _use(monkeypatch, [{"_id": "companion_state",
                        "last_location": now - timedelta(minutes=40)}])
    assert cc.should_speak("location", now) is True


def test_event_enabled_with_legacy_mapping(monkeypatch):
    # arrive_place off → 레거시 arrive_home/arrive_office도 같이 off (표준으로 매핑)
    _use(monkeypatch, [{"_id": "companion",
                        "location_events": {"arrive_place": False}}])
    assert cc.event_enabled("arrive_place") is False
    assert cc.event_enabled("arrive_home") is False    # 레거시 → arrive_place
    assert cc.event_enabled("leave_place") is True      # 미지정 → 디폴트 on
    assert cc.event_enabled("leave_visit") is True      # 레거시 → leave_place
    assert cc.event_enabled("checkin") is True          # 위치 이벤트 아님 → 항상 on
    assert cc.event_enabled("deviate") is True          # 폐기된 이벤트 — 게이트 안 함


def test_set_config_normalizes(monkeypatch):
    _use(monkeypatch)
    out = cc.set_config({
        "location_cooldown_min": "0",   # 문자열 → int, 하한 1로 클램프
        "quiet_start_hour": 99,         # 23으로 클램프
        "enabled": 0,                   # bool
        "location_events": {"arrive_place": False, "bogus": True},  # 미지정 키 무시
    })
    assert out["location_cooldown_min"] == 1
    assert out["quiet_start_hour"] == 23
    assert out["enabled"] is False
    assert out["location_events"]["arrive_place"] is False
    assert "bogus" not in out["location_events"]


def test_mark_spoken_records_time(monkeypatch):
    fake = _use(monkeypatch)
    now = datetime(2026, 6, 16, 12, 0)
    cc.mark_spoken("checkin", now)
    assert fake.docs["companion_state"]["last_checkin"] == now
    cc.mark_spoken("location", now)
    assert fake.docs["companion_state"]["last_location"] == now
