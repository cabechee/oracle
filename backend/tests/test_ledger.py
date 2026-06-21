"""가계부 — 파싱(수입/지출·needs) · merge(영수증↔알림) · 결산 · 반복 · needs 채우기."""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ledger  # noqa: E402


# ── 가짜 ledger 컬렉션 (필요한 쿼리 연산자만) ──
class _Cursor(list):
    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return _Cursor(self[:n])


def _match(d, q):
    for k, v in (q or {}).items():
        cur = d.get(k)
        if isinstance(v, dict):
            if "$ne" in v and cur == v["$ne"]:
                return False
            if "$in" in v and cur not in v["$in"]:
                return False
            if "$nin" in v and cur in v["$nin"]:
                return False
            if "$gte" in v and not (cur is not None and cur >= v["$gte"]):
                return False
            if "$lt" in v and not (cur is not None and cur < v["$lt"]):
                return False
            if "$exists" in v and (k in d) != v["$exists"]:
                return False
        elif cur != v:
            return False
    return True


class _FakeLedger:
    def __init__(self, docs=None):
        self.docs = [dict(x) for x in (docs or [])]

    def find(self, q=None):
        return _Cursor([d for d in self.docs if _match(d, q)])

    def find_one(self, q):
        return next((d for d in self.docs if _match(d, q)), None)

    def insert_one(self, d):
        self.docs.append(dict(d))

    def update_one(self, q, u):
        d = self.find_one(q)
        if d:
            d.update(u.get("$set", {}))

    def delete_one(self, q):
        n = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, q)]
        return type("R", (), {"deleted_count": n - len(self.docs)})()


# ── 파싱 (순수) ──
def test_parse_expense():
    p = ledger.parse_payment("현대카드", "스타벅스 6,000원 일시불 승인됨")
    assert p["kind"] == "expense" and p["amount"] == 6000
    assert p["method"] == "현대카드" and p["merchant"] == "스타벅스" and p["category"] == "카페"
    assert p["complete"] is True


def test_parse_installment():
    p = ledger.parse_payment("현대카드", "the Pink 카드 6,373,440원 10개월 할부 승인됨")
    assert p["amount"] == 6373440 and p["installment"] is True


def test_parse_income():
    p = ledger.parse_payment("토스뱅크", "급여 3,200,000원 입금")
    assert p["kind"] == "income" and p["amount"] == 3200000 and p["needs"] == []


def test_parse_bank_in_out():
    assert ledger.parse_payment("케이뱅크", "입금 500,000원 홍길동")["kind"] == "income"
    assert ledger.parse_payment("토스뱅크", "출금 200,000원 월세")["kind"] == "expense"
    assert ledger.parse_payment("국민은행", "이체 100,000원")["kind"] == "expense"  # 이체출금=지출


def test_parse_excludes_balance():
    # 잔액(running balance)을 거래금액으로 잡지 않음 — 예금이자 4원은 <100이라 노이즈
    assert ledger.parse_payment("신한카드", "예금이자 4원 입금됨, 잔액 19,237원") is None
    p = ledger.parse_payment("신한은행", "급여 입금 2,500,000원, 잔액 3,000,000원")
    assert p["kind"] == "income" and p["amount"] == 2500000        # 잔액 3,000,000 아님
    assert ledger.parse_payment("신한카드", "출금 50,000원 잔액 19,237원")["amount"] == 50000


def test_all_amounts_multi():
    # 한 알림에 두 건이면 둘 다, 잔액·누적은 제외
    assert ledger._all_amounts("31,800원·23,800원 두 건 승인됨", "현대카드 31,800원·23,800원") == [31800, 23800]
    assert ledger._all_amounts("출금 50,000원 잔액 19,237원 누적 200,000원", "x") == [50000]


def test_parse_needs_merchant():
    p = ledger.parse_payment("현대카드", "the Pink 19,000원 승인")
    assert p["kind"] == "expense" and p["merchant"] == "" and p["needs"] == ["merchant"]
    assert p["complete"] is False


def test_parse_non_spend_and_noise():
    assert ledger.parse_payment("토스", "리워드 3000원 적립됨") is None       # 적립
    assert ledger.parse_payment("국세청", "환급액 50,000원 있음") is None      # 환급
    assert ledger.parse_payment("현대카드", "결제 완료") is None              # 금액 없음
    assert ledger.parse_payment("어떤앱", "12,000원 알림") is None            # 결제수단·승인 없음
    assert ledger.parse_payment("현대카드", "이용대금 625,370원 청구") is None  # 청구서(명세, 이중계상)


# ── merge: 영수증 + 카드알림(같은 금액·날짜, 출처 다름) → 합쳐짐 ──
def test_merge_receipt_into_notification(monkeypatch):
    fake = _FakeLedger([{
        "_id": "pay-sig1", "date": "2026-06-21", "kind": "expense", "amount": 23000,
        "method": "현대카드", "merchant": "", "source": "notification",
        "needs": ["merchant"], "complete": False, "signal_ids": ["sig1"],
    }])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    r = ledger.from_receipt("rec-1", datetime(2026, 6, 21, 12, 0),
                            {"amount": 23000, "merchant": "김밥천국", "items": ["제육덮밥", "라면"]})
    assert r == "merged" and len(fake.docs) == 1        # 새로 안 쌓이고 합쳐짐
    d = fake.docs[0]
    assert d["merchant"] == "김밥천국" and d["items"] == ["제육덮밥", "라면"]
    assert d["method"] == "현대카드" and d["needs"] == [] and d["complete"] is True


def test_receipt_no_match_inserts(monkeypatch):
    fake = _FakeLedger([])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    r = ledger.from_receipt("rec-2", datetime(2026, 6, 21, 9, 0),
                            {"amount": 5000, "merchant": "투썸"})
    assert r == "inserted" and len(fake.docs) == 1 and fake.docs[0]["merchant"] == "투썸"


def test_two_notifications_same_amount_not_merged(monkeypatch):
    fake = _FakeLedger([])           # 같은 금액 다른 알림 = 다른 결제, 안 합침
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    ledger._merge_or_insert({"_id": "pay-a", "date": "2026-06-21", "kind": "expense",
                             "amount": 9900, "merchant": "", "source": "notification"})
    ledger._merge_or_insert({"_id": "pay-b", "date": "2026-06-21", "kind": "expense",
                             "amount": 9900, "merchant": "", "source": "notification"})
    assert len(fake.docs) == 2


# ── 결산 + 반복 ──
def test_settlement_income_expense_net(monkeypatch):
    fake = _FakeLedger([
        {"_id": "1", "date": "2026-06-15", "kind": "income", "amount": 3000000},
        {"_id": "2", "date": "2026-06-16", "kind": "expense", "amount": 6000,
         "category": "카페", "method": "현대카드", "merchant": "스타벅스"},
        {"_id": "3", "date": "2026-06-17", "kind": "expense", "amount": 20000,
         "category": "식비", "method": "토스", "merchant": "김밥천국", "needs": ["x"]},
    ])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    s = ledger.settlement("month", date(2026, 6, 21))
    assert s["income"] == 3000000 and s["expense"] == 26000 and s["net"] == 2974000
    cats = {c["name"]: c["amount"] for c in s["by_category"]}
    assert cats["카페"] == 6000 and cats["식비"] == 20000 and s["incomplete"] == 1


def test_recurring_detects_two_months(monkeypatch):
    fake = _FakeLedger([
        {"_id": "n1", "date": "2026-05-03", "kind": "expense", "amount": 17000, "merchant": "넷플릭스"},
        {"_id": "n2", "date": "2026-06-03", "kind": "expense", "amount": 17000, "merchant": "넷플릭스"},
        {"_id": "x1", "date": "2026-06-04", "kind": "expense", "amount": 5000, "merchant": "투썸"},
    ])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    names = {r["merchant"] for r in ledger.recurring(date(2026, 6, 21))}
    assert "넷플릭스" in names and "투썸" not in names      # 두 달 반복만


# ── needs 채우기 + 구 문서 호환 ──
def test_set_fields_completes(monkeypatch):
    fake = _FakeLedger([{"_id": "pay-x", "kind": "expense", "amount": 19000,
                         "merchant": "", "needs": ["merchant"], "complete": False}])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    assert ledger.set_fields("pay-x", {"merchant": "올리브영", "category": "마트·생활"})
    d = fake.docs[0]
    assert d["merchant"] == "올리브영" and d["needs"] == [] and d["complete"] is True


def test_approval_extraction():
    assert ledger._approval_of("현대카드 승인번호 12345678 6,000원 승인") == "12345678"
    assert ledger._approval_of("스타벅스 6,000원 승인") == ""   # 번호 없으면 빈값


def test_merge_by_approval(monkeypatch):
    # 승인번호 같으면 날짜·출처 달라도 한곳에 합침 + 영수증 이미지 둘 다 보존
    fake = _FakeLedger([{
        "_id": "pay-card", "date": "2026-06-19", "kind": "expense", "amount": 50000,
        "method": "현대카드", "merchant": "", "approval_no": "12345678",
        "source": "notification", "needs": ["merchant"], "complete": False,
        "receipt_images": ["images/card.png"],
    }])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    r = ledger.from_receipt("rec-9", datetime(2026, 6, 21, 10, 0), {   # 다른 날 쇼핑몰 영수증
        "amount": 50000, "merchant": "쿠팡", "approval": "12345678", "image": "images/shop.png"})
    assert r == "merged" and len(fake.docs) == 1
    d = fake.docs[0]
    assert d["merchant"] == "쿠팡" and d["approval_no"] == "12345678"
    assert d["amount"] == 100000 and d["amount_parts"] == [50000, 50000]   # 무조건 합산
    assert "images/card.png" in d["receipt_images"] and "images/shop.png" in d["receipt_images"]


def test_approval_sum_distinct_amounts(monkeypatch):
    # 같은 승인번호·다른 금액(쇼핑몰 vs 카드 총액 차이) → 합산 + 부분 금액 보존(diff 판독용)
    fake = _FakeLedger([{
        "_id": "pay-1", "date": "2026-06-20", "kind": "expense", "amount": 10000,
        "merchant": "쿠팡", "approval_no": "999", "source": "receipt",
        "amount_parts": [10000], "receipt_images": ["images/a.png"],
    }])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    ledger.from_receipt("rec-z", datetime(2026, 6, 21, 9, 0), {
        "amount": 8000, "merchant": "쿠팡", "approval": "999", "image": "images/b.png"})
    d = fake.docs[0]
    assert d["amount"] == 18000 and d["amount_parts"] == [10000, 8000]
    assert d["receipt_images"] == ["images/a.png", "images/b.png"]


def test_amount_date_merge_does_not_sum(monkeypatch):
    # 승인번호 없는 카드알림 ↔ 영수증(같은 금액·날짜) → 같은 거래라 금액 유지(합산 X)
    fake = _FakeLedger([{
        "_id": "pay-n", "date": "2026-06-21", "kind": "expense", "amount": 23000,
        "method": "현대카드", "merchant": "", "source": "notification",
        "needs": ["merchant"], "complete": False,
    }])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    ledger.from_receipt("rec-n", datetime(2026, 6, 21, 12, 0),
                        {"amount": 23000, "merchant": "김밥천국"})
    d = fake.docs[0]
    assert d["amount"] == 23000 and not d.get("amount_parts")   # 합산 안 됨


def test_attach_receipt_fills_entry(monkeypatch):
    # 특정 항목에 영수증 붙이기 — 금액은 유지(자동 매칭 X), 가맹점·품목·이미지 채움
    fake = _FakeLedger([{"_id": "pay-x", "kind": "expense", "amount": 23000,
                         "method": "현대카드", "merchant": "", "needs": ["merchant"],
                         "complete": False}])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    row = ledger.attach_receipt("pay-x", {"merchant": "김밥천국", "items": ["라면"],
                                          "image": "images/x.jpg"})
    d = fake.docs[0]
    assert d["merchant"] == "김밥천국" and d["items"] == ["라면"] and d["amount"] == 23000
    assert d["receipt_images"] == ["images/x.jpg"] and d["needs"] == [] and d["complete"] is True
    assert row["merchant"] == "김밥천국"


def test_today_backward_compat_card(monkeypatch):
    fake = _FakeLedger([{"_id": "old", "date": date.today().isoformat(),
                         "amount": 9000, "card": "신한카드", "ts": datetime.now()}])
    monkeypatch.setattr(ledger.db, "ledger", lambda: fake)
    t = ledger.today()
    assert t["expense"] == 9000 and t["items"][0]["method"] == "신한카드"
