"""일 저널 안정성 — 재시도(일시 오류만) + 실패 전파(실패 문자열을 본문으로 저장하지 않음).

20일 일기가 401 인증 오류를 '(일기 생성 실패: …)' 본문째 저장하던 버그의 회귀 방지.
"""

from datetime import date, datetime

import pytest

import journal
from agent import llm


# ── call_retry: 일시 오류만 재시도, 영구 오류·소진은 raise ──────────────

def test_call_retry_success(monkeypatch):
    monkeypatch.setattr(llm, "call", lambda *a, **k: {"text": "x"})
    assert llm.call_retry("a", "p", base_delay=0)["text"] == "x"


def test_call_retry_permanent_no_retry(monkeypatch):
    """401 같은 영구 오류는 재시도해도 같으니 한 번만 시도하고 raise."""
    n = []

    def boom(*a, **k):
        n.append(1)
        raise RuntimeError("API Error: 401 Invalid authentication credentials")

    monkeypatch.setattr(llm, "call", boom)
    with pytest.raises(RuntimeError):
        llm.call_retry("a", "p", tries=3, base_delay=0)
    assert len(n) == 1


def test_call_retry_transient_then_success(monkeypatch):
    """529 과부하는 일시적 — 백오프 재시도하다 성공하면 그 결과를 반환."""
    n = []

    def flaky(*a, **k):
        n.append(1)
        if len(n) < 3:
            raise RuntimeError("API Error: 529 Overloaded")
        return {"text": "ok"}

    monkeypatch.setattr(llm, "call", flaky)
    assert llm.call_retry("a", "p", tries=3, base_delay=0)["text"] == "ok"
    assert len(n) == 3


def test_call_retry_transient_exhausted(monkeypatch):
    """일시 오류라도 tries회 모두 실패하면 raise(호출자가 빈 슬롯 처리)."""
    n = []

    def boom(*a, **k):
        n.append(1)
        raise RuntimeError("529 Overloaded")

    monkeypatch.setattr(llm, "call", boom)
    with pytest.raises(RuntimeError):
        llm.call_retry("a", "p", tries=3, base_delay=0)
    assert len(n) == 3


# ── make_daily_journal: 성공이면 본문, 실패면 전파(실패 문자열 저장 안 함) ──

def _recs():
    return [{"_id": "r1", "ts": datetime(2026, 6, 20, 9, 0), "user_comment": "테스트"}]


@pytest.fixture(autouse=True)
def _no_ledger(monkeypatch):
    # 일기 재료 중 가계부는 db 접근 — 테스트에선 빈 결과로(연결 시도 회피).
    import ledger
    monkeypatch.setattr(ledger, "today", lambda *a, **k: {"items": []})


def test_make_daily_journal_success(monkeypatch):
    monkeypatch.setattr(journal, "resolve_alias", lambda k: "a")
    monkeypatch.setattr(journal.llm, "call_retry", lambda *a, **k: {"text": "오늘 일기 본문"})
    out = journal.make_daily_journal(_recs(), date(2026, 6, 20))
    assert out.startswith("# 2026-06-20")
    assert "오늘 일기 본문" in out
    assert "생성 실패" not in out


def test_make_daily_journal_propagates_failure(monkeypatch):
    """실패는 전파 — 호출자(nightly)가 저장을 건너뛰어 슬롯을 비운다."""
    monkeypatch.setattr(journal, "resolve_alias", lambda k: "a")

    def boom(*a, **k):
        raise RuntimeError("API Error: 401 Invalid authentication credentials")

    monkeypatch.setattr(journal.llm, "call_retry", boom)
    with pytest.raises(RuntimeError):
        journal.make_daily_journal(_recs(), date(2026, 6, 20))


def test_make_daily_journal_empty_response_fails(monkeypatch):
    """빈 응답도 실패로 — 빈 일기를 정상인 양 저장하지 않게."""
    monkeypatch.setattr(journal, "resolve_alias", lambda k: "a")
    monkeypatch.setattr(journal.llm, "call_retry", lambda *a, **k: {"text": "   "})
    with pytest.raises(RuntimeError):
        journal.make_daily_journal(_recs(), date(2026, 6, 20))


# ── 코멘트 반영 재처리: 피드백 블록 주입 ──────────────────────────────

def test_feedback_block():
    from agent import personas
    assert personas.feedback_block("") == ""
    assert personas.feedback_block("   ") == ""
    b = personas.feedback_block("더 짧게 써")
    assert "더 짧게 써" in b and "다시 써" in b


def test_make_daily_journal_injects_comment(monkeypatch):
    cap = {}
    monkeypatch.setattr(journal, "resolve_alias", lambda k: "a")
    monkeypatch.setattr(journal.llm, "call_retry",
                        lambda alias, prompt, **k: cap.update(prompt=prompt) or {"text": "본문"})
    journal.make_daily_journal(_recs(), date(2026, 6, 20), comment="쿠키 호칭을 오빠로")
    assert "쿠키 호칭을 오빠로" in cap["prompt"]


def test_make_daily_journal_no_comment_no_block(monkeypatch):
    cap = {}
    monkeypatch.setattr(journal, "resolve_alias", lambda k: "a")
    monkeypatch.setattr(journal.llm, "call_retry",
                        lambda alias, prompt, **k: cap.update(prompt=prompt) or {"text": "본문"})
    journal.make_daily_journal(_recs(), date(2026, 6, 20))
    assert "다시 쓰기" not in cap["prompt"]
