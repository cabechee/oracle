"""대화 액션(캘린더 일정 등록) — 감지·추출·확인 플로우. LLM·gcal·db 모두 mock."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import actions, chat as chat_mod   # noqa: E402


def test_detect_skips_without_keyword(monkeypatch):
    # 일정 키워드 없으면 LLM 호출조차 안 함(비용 방지) → None
    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(actions.llm, "call", _spy)
    assert actions.detect_calendar("오늘 기분 어때?") is None
    assert calls["n"] == 0


def test_detect_extracts_event(monkeypatch):
    monkeypatch.setattr(actions, "task_alias", lambda k: "x")
    monkeypatch.setattr(actions.llm, "call", lambda *a, **k: {"json": {
        "is_event": True, "title": "치과 예약",
        "start": "2026-06-19T15:00:00+09:00", "end": "2026-06-19T16:00:00+09:00",
        "all_day": False, "location": ""}})
    p = actions.detect_calendar("내일 3시에 치과 예약 넣어줘",
                                now=datetime(2026, 6, 18, 10, 0))
    assert p and p["type"] == "create_event" and p["status"] == "proposed"
    assert p["event"]["title"] == "치과 예약"
    assert "치과 예약" in p["preview"] and "15:00" in p["preview"]


def test_detect_query_is_not_event(monkeypatch):
    # 키워드는 있지만(일정) 조회 → LLM이 is_event=false → None
    monkeypatch.setattr(actions, "task_alias", lambda k: "x")
    monkeypatch.setattr(actions.llm, "call",
                        lambda *a, **k: {"json": {"is_event": False}})
    assert actions.detect_calendar("오늘 일정 뭐 있어?") is None


def test_run_unauthed(monkeypatch):
    monkeypatch.setattr(actions.gcal, "create_event", lambda *a, **k: None)
    r = actions.run({"type": "create_event",
                     "event": {"title": "x", "start": "2026-06-19T15:00:00+09:00"}})
    assert r["ok"] is False and "reason" in r


class _FakeConv:
    def __init__(self):
        self.docs = {}

    def insert_one(self, d):
        self.docs[d["_id"]] = dict(d)

    def find_one(self, flt):
        d = self.docs.get(flt.get("_id"))
        return dict(d) if d else None

    def update_one(self, flt, upd, **kw):
        class _R:
            def __init__(s, n):
                s.matched_count = n
        d = self.docs.get(flt.get("_id"))
        if d is None:
            return _R(0)
        for fk, fv in flt.items():
            if fk == "_id":
                continue
            cur = d
            for part in fk.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            if cur != fv:
                return _R(0)
        for k, v in (upd.get("$set") or {}).items():
            if "." in k:
                a, b = k.split(".", 1)
                d.setdefault(a, {})[b] = v
            else:
                d[k] = v
        return _R(1)


def test_confirm_flow_idempotent(monkeypatch):
    fake = _FakeConv()
    monkeypatch.setattr(chat_mod.db, "conversations", lambda: fake)
    monkeypatch.setattr(actions.gcal, "create_event",
                        lambda *a, **k: {"id": "ev1", "title": "치과 예약"})
    fake.insert_one({"_id": "m1", "role": "assistant", "action": {
        "type": "create_event", "status": "proposed",
        "event": {"title": "치과 예약", "start": "2026-06-19T15:00:00+09:00",
                  "end": None, "all_day": False, "location": ""}}})
    r = chat_mod.confirm_action("m1")
    assert r["ok"] and r["event"]["id"] == "ev1"
    assert fake.docs["m1"]["action"]["status"] == "done"
    # 멱등 — 이미 done이면 다시 만들지 않음(중복 일정 방지)
    assert chat_mod.confirm_action("m1")["ok"] is False


def test_cancel(monkeypatch):
    fake = _FakeConv()
    monkeypatch.setattr(chat_mod.db, "conversations", lambda: fake)
    fake.insert_one({"_id": "m2", "action": {
        "type": "create_event", "status": "proposed", "event": {}}})
    assert chat_mod.cancel_action("m2")["ok"] is True
    assert fake.docs["m2"]["action"]["status"] == "cancelled"
