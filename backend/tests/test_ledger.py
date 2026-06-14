"""ledger 단위 테스트 — 결제 추출 (DB 불요 순수 부분)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ledger  # noqa: E402


def test_parse_payment_basic():
    p = ledger.parse_payment("현대카드", "the Pink로 19,000원 일시불 승인됨")
    assert p is not None
    assert p["amount"] == 19000
    assert p["installment"] is False
    assert p["card"] == "현대카드"


def test_parse_payment_installment():
    p = ledger.parse_payment("현대카드", "the Pink 카드 6,373,440원 10개월 할부 승인됨")
    assert p is not None
    assert p["amount"] == 6373440
    assert p["installment"] is True


def test_parse_payment_excludes_non_spend():
    assert ledger.parse_payment("토스", "리워드 3000원 적립됨") is None       # 적립
    assert ledger.parse_payment("쿠팡이츠", "2000원 쿠폰 곧 사라진다고 함") is None  # 쿠폰
    assert ledger.parse_payment("국세청", "정기신고 환급액 50,000원 있음") is None    # 환급


def test_parse_payment_needs_amount_and_method():
    assert ledger.parse_payment("현대카드", "결제 완료") is None              # 금액 없음
    assert ledger.parse_payment("어떤앱", "12,000원 알림") is None            # 결제수단·승인 없음
    assert ledger.parse_payment("스타벅스", "5,000원 주문 들어옴") is None      # 결제수단 힌트 없음
