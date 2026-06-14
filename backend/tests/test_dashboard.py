"""dashboard 단위 테스트 — 데스크 필터·키 로직 (DB 불요 순수 부분)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dashboard  # noqa: E402


def test_keys_are_stable_and_namespaced():
    assert dashboard._action_key("brief-x", 0) == "action:brief-x#0"
    assert dashboard._action_key("brief-x", 2) == "action:brief-x#2"  # 인덱스로 구분
    assert dashboard._pending_key(3) == "pending:3"
    # 네임스페이스가 갈려 action/pending 키가 섞이지 않음
    assert dashboard._action_key("3", 0) != dashboard._pending_key(3)


def _brief(bid, ts, items):
    return {"_id": bid, "ts": ts, "items": items}


def test_collect_actions_only_action_needed():
    briefs = [_brief("b1", datetime(2026, 6, 14, 9, 0), [
        {"category": "action_needed", "sender": "은행", "summary": "카드 결제 승인"},
        {"category": "attention", "sender": "택배", "summary": "배송 도착"},
        {"category": "spam", "sender": "광고", "summary": "할인"},
    ])]
    out = dashboard._collect_actions(briefs, set())
    assert len(out) == 1                          # action_needed만
    assert out[0]["summary"] == "카드 결제 승인"
    assert out[0]["key"] == "action:b1#0"
    assert out[0]["sender"] == "은행"
    assert out[0]["ts"] == datetime(2026, 6, 14, 9, 0).isoformat()


def test_collect_actions_excludes_dismissed():
    briefs = [_brief("b1", datetime(2026, 6, 14, 9, 0), [
        {"category": "action_needed", "summary": "회신 필요", "sender": "A"},
        {"category": "action_needed", "summary": "예약 확인", "sender": "B"},
    ])]
    # 첫 항목만 확인 처리 → 둘째만 남음
    out = dashboard._collect_actions(briefs, {"action:b1#0"})
    assert [o["summary"] for o in out] == ["예약 확인"]
    assert out[0]["key"] == "action:b1#1"


def test_collect_actions_excludes_inaccurate_feedback():
    briefs = [_brief("b1", datetime(2026, 6, 14, 9, 0), [
        {"category": "action_needed", "summary": "오분류", "sender": "X",
         "feedback": "inaccurate"},
        {"category": "action_needed", "summary": "진짜 액션", "sender": "Y"},
    ])]
    out = dashboard._collect_actions(briefs, set())
    assert [o["summary"] for o in out] == ["진짜 액션"]   # 부정확 표시는 숨김


def test_collect_actions_spans_multiple_briefs():
    briefs = [
        _brief("b2", datetime(2026, 6, 14, 10, 0), [
            {"category": "action_needed", "summary": "둘째 brief", "sender": "B"}]),
        _brief("b1", datetime(2026, 6, 14, 9, 0), [
            {"category": "action_needed", "summary": "첫 brief", "sender": "A"}]),
    ]
    out = dashboard._collect_actions(briefs, set())
    assert len(out) == 2
    keys = {o["key"] for o in out}
    assert keys == {"action:b2#0", "action:b1#0"}      # brief별 고유 키


def test_collect_actions_handles_empty_and_missing_items():
    assert dashboard._collect_actions([], set()) == []
    assert dashboard._collect_actions([{"_id": "b", "ts": None}], set()) == []


def test_collect_actions_dedups_same_signal_across_briefs():
    # 같은 원본 신호(sig-x)가 두 brief에 '다르게' 요약돼도 — race 잔재 — 1건만.
    briefs = [
        _brief("b2", datetime(2026, 6, 13, 21, 41, 33), [
            {"category": "action_needed", "sender": "커버링",
             "summary": "봉투 1개 배출", "signal_ids": ["sig-x", "sig-y"]}]),
        _brief("b1", datetime(2026, 6, 13, 21, 41, 22), [
            {"category": "action_needed", "sender": "커버링",
             "summary": "품목 배출", "signal_ids": ["sig-x", "sig-y"]}]),
    ]
    out = dashboard._collect_actions(briefs, set())
    assert len(out) == 1                          # sig-x 겹쳐 중복 제거
    assert out[0]["summary"] == "봉투 1개 배출"    # 최신(먼저 순회) 유지


def test_collect_actions_dedups_textually_when_no_signal_ids():
    # 구 brief(signal_ids 없음)는 발신자+요약으로 중복 판정
    briefs = [
        _brief("b2", datetime(2026, 6, 13, 10, 0), [
            {"category": "action_needed", "sender": "은행", "summary": "카드 결제"}]),
        _brief("b1", datetime(2026, 6, 13, 9, 0), [
            {"category": "action_needed", "sender": "은행", "summary": "카드 결제"}]),
    ]
    assert len(dashboard._collect_actions(briefs, set())) == 1
