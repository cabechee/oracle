"""가계부 분류 — 규칙(DB) 우선 → 키워드 폴백. 규칙은 시드(쿠팡)+어드민 수정+LLM 주기 업그레이드.

규칙(category_rules): {_id, name, pattern(정규식), fields[merchant|sender|items], category,
  set_merchant?(가맹점 보정), priority(높을수록 먼저), source(seed|manual|llm)}.
분류 흐름: match(규칙) → 있으면 그 분류(+가맹점 보정), 없으면 _keyword(보수적 폴백).
LLM 업그레이드(upgrade): 규칙 안 걸리는 가맹점들을 품목 보고 분류 → 규칙 자동 등록 → 재분류.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import db

# 분류 체계(LLM이 고를 수 있는 집합)
CATEGORIES: List[str] = [
    "식비", "카페", "쇼핑", "마트·생활", "교통", "통신", "주거", "의료",
    "문화", "구독", "금융", "교육", "미용", "경조사", "기타",
]

# 키워드 폴백 — 규칙 없을 때만. 보수적으로(쿠팡 등 거래량 많은 곳은 규칙으로 잡는다).
_KW: List[Tuple[str, str]] = [
    ("카페", r"스타벅스|커피|cafe|카페|투썸|이디야|메가커피|컴포즈|폴바셋|빽다방"),
    ("식비", r"식당|배달|배민|쿠팡이츠|요기요|김밥|국밥|치킨|피자|버거|맥도|롯데리아|분식|"
             r"레스토랑|뷔페|해장|초밥|파스타"),
    ("마트·생활", r"마트|이마트|홈플러스|코스트코|편의점|GS25|\bCU\b|세븐일레븐|다이소|올리브영"),
    ("교통", r"택시|버스|지하철|주유|기름|하이패스|카카오\s*T|타다|쏘카|렌트"),
    ("구독", r"넷플릭스|netflix|유튜브|youtube|멤버십|구독|디즈니|왓챠|스포티|chatgpt|openai"),
    ("의료", r"병원|약국|치과|의원|한의원|클리닉|메디"),
    ("문화", r"영화|cgv|메가박스|롯데시네마|공연|전시|서점|교보|예스24|콘서트"),
]


def seed() -> None:
    """기본 규칙 — 쿠팡(거래량 많음): merchant/sender에 쿠팡·coupang → 쇼핑, 가맹점 '쿠팡'."""
    if not db.category_rules().find_one({"_id": "rule-coupang"}):
        db.category_rules().insert_one({
            "_id": "rule-coupang", "name": "쿠팡", "pattern": r"쿠팡|coupang",
            "fields": ["merchant", "sender"], "category": "쇼핑",
            "set_merchant": "쿠팡", "priority": 100, "source": "seed",
        })


def _rules() -> List[Dict[str, Any]]:
    try:
        return list(db.category_rules().find().sort("priority", -1))
    except Exception:
        return []          # DB 불가(테스트 등) → 규칙 없이 키워드 폴백


def _blob(r: Dict[str, Any], merchant: str, items, sender: str) -> str:
    fields = r.get("fields") or ["merchant", "sender", "items"]
    parts = []
    if "merchant" in fields:
        parts.append(merchant or "")
    if "sender" in fields:
        parts.append(sender or "")
    if "items" in fields:
        parts.append(" ".join(items or []))
    return " ".join(parts)


def match(merchant: str, items=None, sender: str = "") -> Optional[Dict[str, Any]]:
    """규칙 매칭 → {category, merchant(보정값 or None)} or None."""
    for r in _rules():
        try:
            if re.search(r["pattern"], _blob(r, merchant, items, sender), re.I):
                return {"category": r.get("category"), "merchant": r.get("set_merchant")}
        except re.error:
            continue
    return None


def _keyword(merchant: str, items) -> str:
    blob = f"{merchant or ''} {' '.join(items or [])}"
    for name, pat in _KW:
        if re.search(pat, blob, re.I):
            return name
    return ""


def classify(merchant: str, items=None, sender: str = "") -> Dict[str, Any]:
    """→ {category, merchant}. 규칙 우선(가맹점 보정 포함), 없으면 키워드 폴백."""
    hit = match(merchant, items, sender)
    if hit:
        return {"category": hit.get("category") or "", "merchant": hit.get("merchant") or merchant}
    return {"category": _keyword(merchant, items), "merchant": merchant}


# ── 규칙 CRUD (어드민) ──────────────────────────────────────────
def _view(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": r["_id"], "name": r.get("name", ""), "pattern": r.get("pattern", ""),
            "fields": r.get("fields") or ["merchant"], "category": r.get("category", ""),
            "set_merchant": r.get("set_merchant") or "", "priority": r.get("priority", 50),
            "source": r.get("source", "manual")}


def list_rules() -> List[Dict[str, Any]]:
    return [_view(r) for r in _rules()]


def upsert_rule(name: str, pattern: str, category: str, fields=None,
                set_merchant: str = "", priority: int = 50,
                rule_id: Optional[str] = None) -> Dict[str, Any]:
    """규칙 추가/수정. rule_id 없으면 name 기반 새 id."""
    rid = rule_id or f"rule-{re.sub(r'[^0-9A-Za-z가-힣]', '', name)[:24] or 'r'}"
    doc = {"_id": rid, "name": name.strip(), "pattern": pattern.strip(),
           "fields": fields or ["merchant"], "category": category.strip(),
           "set_merchant": (set_merchant or "").strip(), "priority": int(priority),
           "source": "manual"}
    db.category_rules().update_one({"_id": rid}, {"$set": doc}, upsert=True)
    return _view(doc)


def delete_rule(rule_id: str) -> bool:
    return db.category_rules().delete_one({"_id": rule_id}).deleted_count > 0


# ── 전체 재분류 (규칙 적용) ──────────────────────────────────────
def recategorize() -> int:
    """모든 지출에 규칙 재적용 — category + 가맹점 보정. 바뀐 건수 반환."""
    n = 0
    for e in db.ledger().find({"kind": "expense"}):
        res = classify(e.get("merchant", ""), e.get("items"), e.get("sender", ""))
        upd: Dict[str, Any] = {}
        if res["category"] and res["category"] != e.get("category"):
            upd["category"] = res["category"]
        if res["merchant"] and res["merchant"] != e.get("merchant"):
            upd["merchant"] = res["merchant"]
        if upd:
            db.ledger().update_one({"_id": e["_id"]}, {"$set": upd})
            n += 1
    return n


# ── LLM 주기 업그레이드 ──────────────────────────────────────────
_UPGRADE_SYSTEM = (
    "가맹점과 산 품목을 보고 각 가맹점의 지출 분류를 정하라.\n"
    "분류는 반드시 다음 중 하나: " + ", ".join(CATEGORIES) + ".\n"
    "가맹점 이름과 품목 성격을 함께 보고 판단(예: 쿠팡=쇼핑, 스타벅스=카페, GS25=마트·생활).\n"
    "단, **진짜 가맹점만** 넣어라. 다음은 규칙으로 만들지 말고 빼라:\n"
    "- '입금됨·결제·승인·이체' 같은 동사/상태, 뜻 모를 짧은 조각, 지점명만 있는 것(무역센터점 등),\n"
    "  결제대행사(페이레터·다날 등). 확실한 가맹점만, 애매하면 빼라.\n"
    'JSON만 출력: {"rules": [{"merchant": "가맹점", "category": "분류"}]}'
)


def upgrade(alias: str, limit: int = 40) -> Dict[str, Any]:
    """규칙 안 걸리는 가맹점들을 품목 보고 LLM이 분류 → 규칙 등록 → 전체 재분류.

    가맹점 단위(거래량 많아도 1건으로) — 한 번 규칙 만들면 그 가맹점 전부 즉시 적용.
    """
    from agent import llm

    seen: Dict[str, List[str]] = {}
    for e in db.ledger().find({"kind": "expense", "merchant": {"$nin": ["", None]}}):
        m = e["merchant"]
        if m in seen or match(m, e.get("items"), e.get("sender", "")):
            continue                                  # 이미 규칙 있음 → 건너뜀
        seen[m] = (e.get("items") or [])[:5]
        if len(seen) >= limit:
            break
    if not seen:
        return {"added": 0, "merchants": 0, "recategorized": 0}
    payload = [{"merchant": m, "items": it} for m, it in seen.items()]
    try:
        r = llm.call(alias, json.dumps(payload, ensure_ascii=False),
                     system=_UPGRADE_SYSTEM, expect_json=True)
        out = r.get("json") or {}
        proposed = out.get("rules") if isinstance(out, dict) else None
    except Exception as e:
        print(f"[category] LLM 업그레이드 실패: {e}", flush=True)
        proposed = None
    added = 0
    for rr in (proposed or []):
        if not isinstance(rr, dict):
            continue
        m, cat = (rr.get("merchant") or "").strip(), (rr.get("category") or "").strip()
        if not m or cat not in CATEGORIES or m not in seen:
            continue
        rid = f"rule-{re.sub(r'[^0-9A-Za-z가-힣]', '', m)[:24] or 'r'}"
        if db.category_rules().find_one({"_id": rid}):
            continue
        db.category_rules().insert_one({
            "_id": rid, "name": m, "pattern": re.escape(m), "fields": ["merchant"],
            "category": cat, "set_merchant": "", "priority": 50, "source": "llm"})
        added += 1
    n = recategorize() if added else 0
    return {"added": added, "merchants": len(seen), "recategorized": n}
