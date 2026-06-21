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


def test_say_capture_before_context(monkeypatch):
    # 눈앞 캡처가 맥락보다 앞 — 쿠키가 맥락(시간대·옛일, 예: '새벽')에 안 꽂히게.
    cap = {}
    monkeypatch.setattr(quick.personas, "quick_system", lambda: "SYS")
    monkeypatch.setattr(quick.llm, "call",
                        lambda alias, prompt, **k: cap.update(prompt=prompt, kw=k) or {"text": "ok"})
    quick.say("g", user_input="", media=[{"type": "image"}], context="새벽 04:30 기상 기록")
    p = cap["prompt"]
    assert p.index("방금 들어온 것") < p.index("참고용 배경")   # 캡처가 맥락보다 먼저
    assert "사진 속" in p                                      # 사진에 반응하라 명시
    assert cap["kw"].get("images") == [{"type": "image"}]      # 이미지 전달됨


def test_say_no_context_no_block(monkeypatch):
    # 맥락 없으면 배경 블록 안 붙음(글 그대로).
    cap = {}
    monkeypatch.setattr(quick.personas, "quick_system", lambda: "SYS")
    monkeypatch.setattr(quick.llm, "call",
                        lambda alias, prompt, **k: cap.update(prompt=prompt) or {"text": "ok"})
    quick.say("g", user_input="라면")
    assert "참고용 배경" not in cap["prompt"] and "라면" in cap["prompt"]
