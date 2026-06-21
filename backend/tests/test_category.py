"""분류 — 규칙(쿠팡) 우선 · 발신자 매칭 · 키워드 폴백 · 재분류."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import category  # noqa: E402


class _Cur(list):
    def sort(self, *a, **k):
        return _Cur(sorted(self, key=lambda r: -r.get("priority", 0)))


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = [dict(x) for x in (docs or [])]

    def find(self, q=None):
        return _Cur(self.docs)

    def find_one(self, q):
        return next((d for d in self.docs if d.get("_id") == q.get("_id")), None)

    def insert_one(self, d):
        self.docs.append(dict(d))

    def update_one(self, q, u, upsert=False):
        d = self.find_one(q)
        if d:
            d.update(u.get("$set", {}))
        elif upsert:
            self.docs.append({**q, **u.get("$set", {})})

    def delete_one(self, q):
        n = len(self.docs)
        self.docs = [d for d in self.docs if d.get("_id") != q.get("_id")]
        return type("R", (), {"deleted_count": n - len(self.docs)})()

    def count_documents(self, q):
        return len(self.docs)


_COUPANG = {"_id": "rule-coupang", "name": "쿠팡", "pattern": r"쿠팡|coupang",
            "fields": ["merchant", "sender"], "category": "쇼핑",
            "set_merchant": "쿠팡", "priority": 100}


def test_coupang_rule(monkeypatch):
    monkeypatch.setattr(category.db, "category_rules", lambda: _FakeColl([_COUPANG]))
    r = category.classify("쿠팡(주)", ["충전 케이블"])
    assert r["category"] == "쇼핑" and r["merchant"] == "쿠팡"     # 분류 + 가맹점 보정


def test_coupang_by_sender(monkeypatch):
    # 가맹점 비어도 발신자 payment.coupang → 쿠팡·쇼핑
    monkeypatch.setattr(category.db, "category_rules", lambda: _FakeColl([_COUPANG]))
    r = category.classify("", ["뭔가"], "payment.coupang")
    assert r["category"] == "쇼핑" and r["merchant"] == "쿠팡"


def test_coupang_not_misclassified_as_food(monkeypatch):
    # 쿠팡인데 품목에 '소고기' 있어도 식비 아님 → 쇼핑(규칙 우선)
    monkeypatch.setattr(category.db, "category_rules", lambda: _FakeColl([_COUPANG]))
    assert category.classify("쿠팡(주)", ["소고기 500g", "삼겹살"])["category"] == "쇼핑"


def test_keyword_fallback(monkeypatch):
    monkeypatch.setattr(category.db, "category_rules", lambda: _FakeColl([]))
    assert category.classify("스타벅스", ["아메리카노"])["category"] == "카페"
    assert category.classify("듣보상점", ["뭔가"])["category"] == ""   # 못 잡으면 빈값(LLM이 채움)


def test_recategorize_applies_rule(monkeypatch):
    rules = _FakeColl([_COUPANG])
    led = _FakeColl([
        {"_id": "a", "kind": "expense", "merchant": "쿠팡(주)", "items": ["케이블"], "category": "식비"},
        {"_id": "b", "kind": "expense", "merchant": "스타벅스", "items": ["라떼"], "category": ""},
    ])
    monkeypatch.setattr(category.db, "category_rules", lambda: rules)
    monkeypatch.setattr(category.db, "ledger", lambda: led)
    changed = category.recategorize()
    assert changed == 2
    a = led.find_one({"_id": "a"})
    assert a["category"] == "쇼핑" and a["merchant"] == "쿠팡"      # 식비 → 쇼핑, 가맹점 보정
    assert led.find_one({"_id": "b"})["category"] == "카페"        # 키워드 폴백


def test_upsert_and_delete_rule(monkeypatch):
    rules = _FakeColl([])
    monkeypatch.setattr(category.db, "category_rules", lambda: rules)
    v = category.upsert_rule("올리브영", "올리브영", "미용")
    assert v["category"] == "미용" and rules.count_documents({}) == 1
    assert category.delete_rule(v["id"]) and rules.count_documents({}) == 0
