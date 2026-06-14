"""agent.quick.say — 쿠키의 짧은 한마디 (페르소나). 텍스트 strip + 빈 응답 처리."""

from agent import quick


def test_say_strips_text(monkeypatch):
    monkeypatch.setattr(quick.personas, "quick_system", lambda: "SYS")
    monkeypatch.setattr(quick.llm, "call", lambda *a, **k: {"text": "  한마디  "})
    assert quick.say("gemini", user_input="라면") == "한마디"


def test_say_empty_response(monkeypatch):
    monkeypatch.setattr(quick.personas, "quick_system", lambda: "SYS")
    monkeypatch.setattr(quick.llm, "call", lambda *a, **k: {"text": ""})
    assert quick.say("gemini") == ""
