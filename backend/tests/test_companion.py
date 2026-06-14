"""agent.companion.say — 이벤트 → 쿠키/베르 한마디. 화자 선택·실패 graceful."""

from agent import companion


def _patch(monkeypatch, text="집 왔구나!"):
    monkeypatch.setattr(companion.personas, "current", lambda k: "SYS")
    monkeypatch.setattr(companion, "task_alias", lambda k: "haiku")
    monkeypatch.setattr(companion.llm, "call", lambda *a, **k: {"text": text})


def test_say_cookie(monkeypatch):
    _patch(monkeypatch)
    r = companion.say("arrive_home", speaker="cookie")
    assert r["speaker"] == "쿠키"
    assert r["text"] == "집 왔구나!"


def test_say_berr(monkeypatch):
    _patch(monkeypatch, text="뭐 해?")
    r = companion.say("checkin", speaker="berr")
    assert r["speaker"] == "베르"
    assert r["text"] == "뭐 해?"


def test_say_unknown_event_ok(monkeypatch):
    _patch(monkeypatch)
    r = companion.say("???", speaker="cookie")  # 미정의 이벤트도 graceful
    assert r["speaker"] == "쿠키"


def test_say_no_alias(monkeypatch):
    monkeypatch.setattr(companion.personas, "current", lambda k: "SYS")
    monkeypatch.setattr(companion, "task_alias", lambda k: "")  # 미설정
    r = companion.say("checkin", speaker="berr")
    assert r["text"] == ""
