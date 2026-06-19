"""gcal 단위 — 구글 서비스 mock으로 파싱·필터·생성·graceful 검증(실제 호출 없음)."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gcal  # noqa: E402


class _Req:
    def __init__(self, result):
        self._r = result

    def execute(self):
        return self._r


class _Events:
    def __init__(self, items):
        self.items = items
        self.inserted = None

    def list(self, **kw):
        return _Req({"items": self.items})

    def insert(self, calendarId=None, body=None):
        self.inserted = body
        out = dict(body)
        out["id"] = "newid"
        out["htmlLink"] = "http://example/x"
        return _Req(out)


class _Svc:
    def __init__(self, items):
        self._e = _Events(items)

    def events(self):
        return self._e


def _fixture():
    today = date.today().isoformat()
    return [
        {"summary": "치과 예약",
         "start": {"dateTime": f"{today}T14:00:00+09:00"},
         "end": {"dateTime": f"{today}T14:30:00+09:00"},
         "location": "서울S치과"},
        {"summary": "워크숍", "start": {"date": today}, "end": {"date": today}},
    ]


def _reset():
    gcal._CACHE["events"] = None
    gcal._CACHE["at"] = None


def test_upcoming_views(monkeypatch):
    _reset()
    monkeypatch.setattr(gcal, "_service", lambda: _Svc(_fixture()))
    evs = gcal.upcoming(use_cache=False)
    assert len(evs) == 2
    assert evs[0]["title"] == "치과 예약" and evs[0]["all_day"] is False
    assert evs[0]["location"] == "서울S치과"
    assert evs[1]["all_day"] is True


def test_day_lines(monkeypatch):
    _reset()
    monkeypatch.setattr(gcal, "_service", lambda: _Svc(_fixture()))
    lines = gcal.day_lines()
    assert any("14:00 치과 예약" in ln for ln in lines)
    assert any("종일 워크숍" in ln for ln in lines)


def test_graceful_unauthed(monkeypatch):
    _reset()
    monkeypatch.setattr(gcal, "_service", lambda: None)
    assert gcal.upcoming(use_cache=False) == []
    assert gcal.today_events() == []
    assert gcal.create_event("x", "2026-06-20T10:00:00+09:00") is None


def test_create_timed(monkeypatch):
    _reset()
    svc = _Svc([])
    monkeypatch.setattr(gcal, "_service", lambda: svc)
    ev = gcal.create_event("미팅", "2026-06-20T10:00:00+09:00",
                           "2026-06-20T11:00:00+09:00", location="회의실")
    assert ev and ev["title"] == "미팅"
    assert svc._e.inserted["start"]["dateTime"] == "2026-06-20T10:00:00+09:00"
    assert svc._e.inserted["location"] == "회의실"


def test_create_all_day(monkeypatch):
    _reset()
    svc = _Svc([])
    monkeypatch.setattr(gcal, "_service", lambda: svc)
    gcal.create_event("휴가", "2026-06-20", all_day=True)
    assert svc._e.inserted["start"]["date"] == "2026-06-20"
    assert svc._e.inserted["end"]["date"] == "2026-06-21"   # 종일 end=다음날


def test_status_unauthed(monkeypatch):
    monkeypatch.setattr(gcal, "_load_creds", lambda: None)
    s = gcal.status()
    assert s["authed"] is False and "calendar_id" in s
