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


# ── 호칭 일관성: 계기·장면 속 '아빠'가 쿠키 프롬프트에 새지 않아야 ('오빠, 아빠…' 버그) ──
def _capture_speak_prompt(monkeypatch, ctx=""):
    cap = {}
    monkeypatch.setattr(companion.personas, "current", lambda k: "SYS")
    monkeypatch.setattr(companion, "task_alias", lambda k: "haiku")
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: True)
    monkeypatch.setattr(companion.cc, "gather_context", lambda *a, **k: ctx)
    monkeypatch.setattr(companion.cc, "mark_spoken", lambda *a, **k: None)
    monkeypatch.setattr(companion.llm, "call",
                        lambda alias, prompt, system=None: cap.update(prompt=prompt) or {"text": "ok"})
    return cap


def test_speak_cookie_no_appa_leak(monkeypatch):
    # 쿠키면 계기·맥락의 '아빠'가 '오빠'로 치환 → 프롬프트에 '아빠' 안 남음(섞임 방지).
    cap = _capture_speak_prompt(monkeypatch, ctx="아빠가 오늘 3곳 다녀옴")
    companion._speak("car", "아빠가 차 몰고 회사 가는 중이야.", speaker="cookie")
    assert "아빠" not in cap["prompt"] and "오빠" in cap["prompt"]


def test_speak_berr_keeps_appa(monkeypatch):
    # 베르면 '아빠' 유지(치환 안 함).
    cap = _capture_speak_prompt(monkeypatch, ctx="아빠가 오늘 3곳 다녀옴")
    companion._speak("car", "아빠가 차 몰고 회사 가는 중이야.", speaker="berr")
    assert "아빠" in cap["prompt"]


def test_banter_scene_neutralized(monkeypatch):
    # banter 장면 서술의 '아빠'는 '그분'으로 중립화(쿠키가 베껴 '아빠' 쓰는 것 방지).
    cap = {}
    monkeypatch.setattr(companion.personas, "current", lambda k: "SYS")
    monkeypatch.setattr(companion, "task_alias", lambda k: "haiku")
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: True)
    monkeypatch.setattr(companion.places_mod, "lookup", lambda p: {"name": p, "kind": "office"})
    monkeypatch.setattr(companion.llm, "call",
                        lambda alias, prompt, system=None: cap.update(prompt=prompt) or {"text": "[]"})
    companion.banter("arrive", "작업실")
    scene_part = cap["prompt"].split("[지금 상황]")[1].split("\n\n")[0]
    assert "아빠" not in scene_part and "그분" in scene_part   # 장면 서술 중립화


# ── 흐름 발화 재처리 — regen 맥락으로 코멘트 반영해 그 자리에서 교체 ──
class _FakeConv:
    def __init__(self, doc=None):
        self.doc = doc
        self.updated = None

    def find_one(self, q):
        return self.doc

    def update_one(self, q, u):
        self.updated = u


def test_reprocess_companion_with_regen(monkeypatch):
    doc = {"_id": "cmsg-x", "speaker": "베르", "companion": True, "text": "옛 말",
           "regen": {"kind": "car", "situation": "아빠가 회사 가는 중", "speaker": "berr"}}
    conv = _FakeConv(doc)
    monkeypatch.setattr(companion.db, "conversations", lambda: conv)
    cap = _capture_speak_prompt(monkeypatch)
    out = companion.reprocess_companion("cmsg-x", comment="더 다정하게")
    assert out["ok"] is True
    assert out["text"] == "ok"                          # _speak mock 반환으로 교체
    assert conv.updated["$set"]["text"] == "ok"         # 그 자리에서 갱신
    assert "더 다정하게" in cap["prompt"]                # 코멘트가 프롬프트에 주입


def test_reprocess_companion_not_found(monkeypatch):
    monkeypatch.setattr(companion.db, "conversations", lambda: _FakeConv(None))
    assert companion.reprocess_companion("nope") is None


def test_reprocess_companion_force_bypasses_gate(monkeypatch):
    # 게이팅이 닫혀 있어도 재처리는 force=True라 생성된다(사용자가 명시 요청).
    doc = {"_id": "bmsg-y", "speaker": "쿠키", "companion": True, "text": "옛",
           "regen": {"kind": "banter", "situation": "그분 도착", "speaker": "cookie"}}
    conv = _FakeConv(doc)
    monkeypatch.setattr(companion.db, "conversations", lambda: conv)
    monkeypatch.setattr(companion.personas, "current", lambda k: "SYS")
    monkeypatch.setattr(companion, "task_alias", lambda k: "haiku")
    monkeypatch.setattr(companion.cc, "should_speak", lambda *a, **k: False)   # 닫힘
    monkeypatch.setattr(companion.cc, "gather_context", lambda *a, **k: "")
    monkeypatch.setattr(companion.cc, "mark_spoken", lambda *a, **k: None)
    monkeypatch.setattr(companion.llm, "call", lambda *a, **k: {"text": "새 말"})
    out = companion.reprocess_companion("bmsg-y", comment="짧게")
    assert out["ok"] is True and out["text"] == "새 말"


def test_reprocess_companion_no_regen_uses_trigger(monkeypatch):
    # regen 없는 과거 발화 — trigger·기존 말로 맥락 근사.
    doc = {"_id": "cmsg-z", "speaker": "베르", "companion": True,
           "text": "원래 말", "trigger": "집 도착"}
    conv = _FakeConv(doc)
    monkeypatch.setattr(companion.db, "conversations", lambda: conv)
    cap = _capture_speak_prompt(monkeypatch)
    out = companion.reprocess_companion("cmsg-z", comment="짧게")
    assert out["ok"] is True
    assert "집 도착" in cap["prompt"] and "원래 말" in cap["prompt"]
