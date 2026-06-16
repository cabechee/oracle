"""agent.companion.say — 이벤트 → 쿠키/베르 한마디. 화자 선택·실패 graceful."""

from agent import companion


def _patch(monkeypatch, text="집 왔구나!"):
    monkeypatch.setattr(companion.personas, "current", lambda k: "SYS")
    monkeypatch.setattr(companion, "task_alias", lambda k: "haiku")
    monkeypatch.setattr(companion.llm, "call", lambda *a, **k: {"text": text})
    # 게이팅·맥락은 별도 모듈(companion_config) — say 단위테스트에선 통과시키고 격리
    monkeypatch.setattr(companion.cc, "event_enabled", lambda *a, **k: True)
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: True)
    monkeypatch.setattr(companion.cc, "gather_context", lambda *a, **k: "")
    monkeypatch.setattr(companion.cc, "mark_spoken", lambda *a, **k: None)


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
    monkeypatch.setattr(companion.cc, "event_enabled", lambda *a, **k: True)
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: True)
    r = companion.say("checkin", speaker="berr")
    assert r["text"] == ""


def test_say_gated(monkeypatch):
    # 게이팅(텀·조용구간 등)에 걸리면 LLM 호출 없이 빈 text + gated 플래그.
    monkeypatch.setattr(companion.cc, "event_enabled", lambda *a, **k: True)
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: False)
    monkeypatch.setattr(companion.llm, "call",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM 호출되면 안 됨")))
    r = companion.say("checkin", speaker="berr")
    assert r["text"] == ""
    assert r.get("gated") is True


def test_say_event_off(monkeypatch):
    # 이벤트별 off(예: 장소 도착)면 위치 말 걸기여도 억제.
    monkeypatch.setattr(companion.cc, "event_enabled", lambda e, *a, **k: e != "arrive_place")
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: True)
    r = companion.say("arrive_place", speaker="cookie")
    assert r["text"] == ""


def test_situation_known_vs_new(monkeypatch):
    # 저장된 장소면 이름·설명을 녹이고, 미등록이면 '새로운 곳'으로.
    monkeypatch.setattr(companion.places_mod, "lookup",
                        lambda k: {"name": "단골카페", "description": "라떼 맛집"}
                        if k == "단골카페" else None)
    s1 = companion._situation("arrive_place", "단골카페", 30)
    assert "단골카페" in s1 and "라떼 맛집" in s1 and "30분" in s1
    s2 = companion._situation("arrive_place", None, None)
    assert "새로운 곳" in s2
    s3 = companion._situation("leave_place", "단골카페", None)
    assert "단골카페" in s3 and "나서" in s3
    s4 = companion._situation("checkin", None, None)
    assert "궁금" in s4
    # 레거시 이벤트명도 도착/나섬으로 동작
    assert "단골카페" in companion._situation("arrive_home", "단골카페", None)


# ── record_asked — 동반자 선제 멘트를 흐름에 남김 (탭해 들어온 시각으로) ──
from datetime import datetime


def test_ts_to_dt_forms():
    assert isinstance(companion._ts_to_dt(1718000000000), datetime)   # epoch ms
    assert companion._ts_to_dt("2026-06-15T10:00:00").hour == 10      # ISO
    assert isinstance(companion._ts_to_dt(None), datetime)            # graceful
    assert isinstance(companion._ts_to_dt("nope"), datetime)          # graceful


class _FakeCol:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(doc)


def test_record_asked(monkeypatch):
    col = _FakeCol()
    monkeypatch.setattr(companion.db, "conversations", lambda: col)
    out = companion.record_asked("베르", "  아빠 뭐해요?  ", 1718000000000)
    assert out["role"] == "assistant"      # 흐름에서 동반자 발화로 렌더
    assert out["speaker"] == "베르"
    assert out["companion"] is True        # 대화 응답과 구분
    assert out["text"] == "아빠 뭐해요?"    # trim
    assert isinstance(out["ts"], str)      # ISO 직렬화
    assert len(col.docs) == 1              # conversations에 1건 저장
    assert col.docs[0]["_id"].startswith("cmsg-")
