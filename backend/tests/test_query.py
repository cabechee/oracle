"""query 모듈 단위 테스트 — referenced 추출 (query/chat 공용 헬퍼)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from query import extract_referenced


def test_extract_referenced_basic():
    text = "마우스는 6월 3일에 찍으셨어요.\n\nreferenced: [rec-20260603-081214-abc123]"
    body, refs = extract_referenced(text)
    assert refs == ["rec-20260603-081214-abc123"]
    assert "referenced" not in body
    assert "마우스" in body


def test_extract_referenced_multiple_and_backticks():
    text = "두 건 있어요.\n`referenced: [rec-20260601-1, rec-20260602-2]`"
    body, refs = extract_referenced(text)
    assert refs == ["rec-20260601-1", "rec-20260602-2"]
    assert "referenced" not in body


def test_extract_referenced_absent():
    body, refs = extract_referenced("기록에 없어요.")
    assert refs == []
    assert body == "기록에 없어요."
