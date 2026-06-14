"""signals 단위 테스트 — OTP 필터·결정적 id·프롬프트 (DB/LLM 불요 부분만)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import signals  # noqa: E402


def test_otp_detection():
    assert signals._is_otp("[Web발신] 인증번호 [483920]을 입력해주세요")
    assert signals._is_otp("Your verification code is 029384")
    assert not signals._is_otp("내일 3시에 보자")          # 키워드 없음
    assert not signals._is_otp("인증번호가 곧 발송됩니다")   # 숫자 없음
    assert not signals._is_otp("계좌로 50000원 입금됨")     # 숫자만, 키워드 없음


def test_signal_id_deterministic_and_distinct():
    a1 = signals._signal_id("sms", "010-1111", 1718000000000, "안녕")
    a2 = signals._signal_id("sms", "010-1111", 1718000000000, "안녕")
    b = signals._signal_id("sms", "010-1111", 1718000000001, "안녕")
    assert a1 == a2          # 같은 신호 → 같은 id (dedupe)
    assert a1 != b           # ts 다르면 다른 id
    assert a1.startswith("sig-")


def test_brief_prompt_shape():
    items = [
        {"_id": "sig-a", "kind": "sms", "sender": "010-2222",
         "body": "내일 회의 10시로 변경", "ts": datetime(2026, 6, 11, 9, 30)},
        {"_id": "sig-b", "kind": "missed_call", "sender": "엄마", "body": "",
         "ts": datetime(2026, 6, 11, 9, 50)},
    ]
    p = signals._brief_prompt(items)
    assert "2건" in p and "내일 회의 10시로 변경" in p
    assert "부재중 전화" in p and "09:50" in p
    assert "sig-a" in p          # id가 프롬프트에 포함돼야 LLM이 signal_ids 매칭


def test_parse_items_validates_category_and_ids():
    valid = {"sig-a", "sig-b"}
    raw = {"items": [
        {"category": "action_needed", "sender": "병원", "summary": "예약 확인",
         "signal_ids": ["sig-a", "sig-x"]},          # sig-x는 무효 → 걸러짐
        {"category": "garbage", "sender": "광고", "summary": "할인",
         "signal_ids": ["sig-b"]},                    # 무효 카테고리 → low
    ]}
    items = signals._parse_items(raw, valid)
    assert len(items) == 2
    assert items[0]["category"] == "action_needed"   # 우선순위 정렬: action 먼저
    assert items[0]["signal_ids"] == ["sig-a"]        # 무효 id 제거
    assert items[1]["category"] == "low"              # garbage → low
    assert all(it["feedback"] is None for it in items)


def test_compose_summary_prioritizes_action():
    items = [
        {"category": "spam", "summary": "광고", "signal_ids": []},
        {"category": "action_needed", "summary": "카드 미납", "signal_ids": []},
        {"category": "low", "summary": "데이터 선물", "signal_ids": []},
    ]
    s = signals._compose_summary(items)
    assert "카드 미납" in s and "당장 액션" in s     # action 노출
    assert "스팸 1" in s and "일반 1" in s            # spam/low는 카운트로


def test_to_dt_graceful():
    assert signals._to_dt("not-a-number") is None
    assert signals._to_dt(None) is None
    assert signals._to_dt(1718000000000) is not None


def test_dedup_signals_collapses_same_sender_body():
    pending = [
        {"_id": "s1", "kind": "notification", "sender": "커버링", "body": "쓰레기 수거"},
        {"_id": "s2", "kind": "notification", "sender": "커버링", "body": "쓰레기 수거"},  # 중복
        {"_id": "s3", "kind": "notification", "sender": "커버링", "body": "다른 내용"},
        {"_id": "s4", "kind": "sms", "sender": "커버링", "body": "쓰레기 수거"},  # kind 달라 별개
    ]
    out = signals._dedup_signals(pending)
    assert len(out) == 3                        # s1(=s2 흡수), s3, s4
    assert out[0]["_id"] == "s1"                # 대표는 먼저 온 것


def test_dedup_signals_keeps_distinct_senders():
    pending = [
        {"_id": "a", "kind": "sms", "sender": "엄마", "body": "밥 먹었니"},
        {"_id": "b", "kind": "sms", "sender": "아빠", "body": "밥 먹었니"},  # 발신자 다름
    ]
    assert len(signals._dedup_signals(pending)) == 2
