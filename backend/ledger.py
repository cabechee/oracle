"""가계부 — 결제·입금 알림과 영수증에서 수입/지출을 구조화해 누적.

대신 읽어드림이 모은 신호 중 '결제/승인/출금/입금'을 가계부 항목으로 떨군다. signal id
기준 멱등(같은 결제 두 번 안 쌓임). 흐름에 올린 영수증 사진도 비전으로 추출해 같은 결제에
merge(금액+날짜 매칭, 출처가 다를 때)한다. 부족한 정보(needs)는 데스크가 '확인필요'로
물어 채우고, 주/월 결산은 settlement()가 대차대조표 형태로 만든다.

스키마(ledger 컬렉션):
  _id, date(YYYY-MM-DD), ts, kind(expense|income), amount(int), method(결제수단/기관),
  merchant(가맹점), category, items[], installment, memo, recurring,
  source(notification|receipt|merged), complete(bool), needs[], signal_ids[], record_id
"""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import db

_AMOUNT = re.compile(r"(\d[\d,]*)\s*원")          # 1원~ 한 자리도(작은 건 parse에서 노이즈로 거름)
# 잔액·누적·한도 등(running balance/누계) — 거래 금액 아님. 금액 추출 전에 떼낸다.
_BALANCE = re.compile(
    r"(?:잔액|잔고|balance|누적|누계|이용\s*한도|한도|이번\s*달|당월|사용\s*액)\s*[:\s]*[\d,]+\s*원",
    re.I)
# 승인번호(approval no) — 거래 고유키. 영수증·카드알림이 둘 다 가지면 강력 매칭.
_APPROVAL = re.compile(r"(?:승인\s*번호|승인\s*no|approval\s*(?:no|number)?)\s*[:#\s]*(\d{4,})", re.I)
_INCOME = re.compile(r"입금|급여|월급|상여|들어왔|받았")            # 돈 들어옴(수입)
_OUT = re.compile(r"승인|결제|출금|구매|결제완료|납부|송금")        # 돈 나감(지출); 이체는 방향 따로
# 비지출 오탐(적립·쿠폰·환급·광고 등) — 실제 입금은 '입금'으로 따로 들어옴
_NON_SPEND = re.compile(r"적립|쿠폰|환급|할인|광고|이벤트|당첨|포인트")
# 카드 청구서·명세(개별 결제 아닌 합계 통지) — 이중계상 방지로 제외
_STATEMENT = re.compile(r"이용대금|청구금액|청구서|결제예정|명세서|총\s*이용|대금\s*명세|"
                        r"이용\s*내역\s*안내|결제\s*예정\s*금액|정기결제\s*안내")
_INSTALL = re.compile(r"할부")
# 결제수단 힌트 — 지출인데 이게 없으면 보류(오탐 방지)
_PAYMENT_HINT = re.compile(
    r"카드|페이|뱅크|은행|카카오|토스|현대|삼성|국민|신한|롯데|우리|하나|BC|페이코|"
    r"체크|신용|일시불|할부|계좌|출금|이체")

# 결제수단/기관 정규화 — 위에서부터 첫 매칭
_METHODS: List[Tuple[str, str]] = [
    ("현대카드", r"현대"), ("삼성카드", r"삼성"), ("국민카드", r"국민|\bKB\b"),
    ("신한카드", r"신한"), ("롯데카드", r"롯데"), ("우리카드", r"우리"),
    ("하나카드", r"하나"), ("BC카드", r"\bBC\b|비씨"),
    ("토스", r"토스|toss"), ("카카오페이", r"카카오\s*페이|kakaopay"),
    ("네이버페이", r"네이버\s*페이|naverpay"), ("페이코", r"페이코|payco"),
    ("계좌이체", r"계좌|이체|출금"), ("현금", r"현금"),
]

# 가벼운 카테고리 추정 (가맹점·요약 키워드)
_CATEGORIES: List[Tuple[str, str]] = [
    ("카페", r"스타벅스|커피|cafe|카페|투썸|이디야|메가커피|컴포즈|폴바셋|빽다방"),
    ("식비", r"식당|배달|배민|쿠팡이츠|요기요|김밥|국밥|치킨|피자|버거|맥도|롯데리아|분식|"
             r"음식|레스토랑|뷔페|해장|고기|초밥|파스타"),
    ("마트·생활", r"마트|이마트|홈플러스|코스트코|편의점|GS25|\bCU\b|세븐일레븐|다이소|올리브영"),
    ("교통", r"택시|버스|지하철|교통|주유|기름|하이패스|주차|카카오\s*T|타다|쏘카|렌트"),
    ("쇼핑", r"쿠팡|11번가|지마켓|옥션|무신사|29CM|쇼핑|백화점|아울렛|스토어"),
    ("구독", r"넷플릭스|netflix|유튜브|youtube|멤버십|구독|디즈니|왓챠|스포티|애플|구글|아마존|chatgpt|openai"),
    ("의료", r"병원|약국|치과|의원|한의원|클리닉|메디"),
    ("문화", r"영화|cgv|메가박스|롯데시네마|공연|전시|서점|교보|예스24|콘서트"),
]


def _method_of(sender: str, text: str) -> str:
    for name, pat in _METHODS:
        if re.search(pat, sender) or re.search(pat, text):
            return name
    return (sender or "").strip() or "기타"


def _category_of(merchant: str, summary: str) -> str:
    blob = f"{merchant} {summary}"
    for name, pat in _CATEGORIES:
        if re.search(pat, blob, re.I):
            return name
    return ""


# 가맹점 오인식 잡토큰 — 카드알림 요약엔 가맹점이 깔끔히 안 들어있는 경우가 많아 보수적으로.
_MERCHANT_STOP = {
    "카드", "결제", "승인", "건", "개월", "일시불", "할부", "원", "구매", "사용", "님", "고객",
    "체크", "신용", "페이", "뱅크", "은행", "월", "일", "시", "분", "해외", "국내", "온라인",
    "the", "pink", "metal", "발신", "web", "웹", "출금", "입금", "이체", "금액", "정상",
}


def _merchant_of(summary: str) -> str:
    """요약에서 가맹점 best-effort — 깨끗한 상호만. 애매하면 ''(needs/영수증 merge로 채움).

    카드알림 요약엔 가맹점이 안 들어있는 경우가 많다 → 할부개월·날짜·숫자·결제수단·잡토큰을
    걸러내고 '확실한 상호'만 반환. 그래야 데스크 '확인필요'·영수증 merge가 제 역할을 한다.
    """
    s = _AMOUNT.sub(" ", summary or "")
    s = re.sub(r"\d+\s*개월|\d+\s*월|\d+\s*일|\d+\s*시|\d+:\d+|\d+/\d+|\d+", " ", s)  # 할부·날짜·시각·숫자
    s = re.sub(r"the\s*\w+", " ", s, flags=re.I)         # 카드 별칭(the Pink/Metal 등)
    s = re.sub(r"승인|결제완료|결제|출금|이체|구매|납부|완료|일시불|할부|에서|으로부터|으로|에게|님|로|에",
               " ", s)
    for _, pat in _METHODS:
        s = re.sub(pat, " ", s, flags=re.I)
    s = re.sub(r"[\[\]()·,~\-:/]", " ", s)
    for t in s.split():
        if len(t) >= 2 and not t.replace(",", "").isdigit() and t.lower() not in _MERCHANT_STOP:
            return t
    return ""


def _approval_of(text: str) -> str:
    """승인번호 추출(없으면 ''). 거래 고유키 — 같은 승인번호면 같은 결제."""
    m = _APPROVAL.search(text or "")
    return m.group(1) if m else ""


def _amount_of(summary: str, text: str) -> Optional[int]:
    """거래 금액 — '잔액/잔고'(running balance)는 빼고 첫 금액. 못 찾으면 None.
    예) '예금이자 4원 입금됨, 잔액 19,237원' → 4 (잔액 19,237 아님)."""
    a = _all_amounts(summary, text)
    return a[0] if a else None


def _all_amounts(summary: str, text: str) -> List[int]:
    """거래 금액 전부(>=100, 중복 제거) — 잔액·누적·한도 제외.
    한 알림에 'A원·B원 두 건'이면 [A, B] (건마다 따로 기록)."""
    src = _BALANCE.sub(" ", summary or "")
    if not _AMOUNT.search(src):
        src = _BALANCE.sub(" ", text or "")
    out: List[int] = []
    for m in _AMOUNT.finditer(src):
        try:
            v = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if v >= 100 and v not in out:
            out.append(v)
    return out


# ── 파싱: 신호 한 줄 → 수입/지출 구조 ────────────────────────────
def parse_payment(sender: str, summary: str) -> Optional[Dict[str, Any]]:
    """신호 한 줄에서 수입/지출을 추출. 아니면 None.

    예) ("현대카드", "스타벅스 6,000원 일시불 승인됨")
        → {kind:expense, amount:6000, method:"현대카드", merchant:"스타벅스", ...}
        ("토스뱅크", "급여 3,200,000원 입금") → {kind:income, ...}
    """
    sender = sender or ""
    summary = summary or ""
    text = f"{sender} {summary}"
    if _NON_SPEND.search(text) or _STATEMENT.search(text):
        return None
    # 수입/지출 방향 — 은행 입/출금·이체도 포함. 입금=수입, 출금·결제·송금=지출,
    # 이체는 입금이면 수입 아니면 지출.
    has_in = bool(_INCOME.search(text))
    has_out = bool(_OUT.search(text))
    transfer = "이체" in text
    if has_in and not has_out:
        is_income = True
    elif has_out or (transfer and not has_in):
        is_income = False
    else:
        return None                          # 결제·입출금 신호 아님
    amount = _amount_of(summary, text)     # 잔액 제외, 한 자리도 인식
    if amount is None or amount < 100:     # 못 찾거나 너무 작으면(예금이자 등 노이즈)
        return None
    if not is_income and not _PAYMENT_HINT.search(text):
        return None
    method = _method_of(sender, text)
    merchant = "" if is_income else _merchant_of(summary)
    needs: List[str] = []
    if not is_income and not merchant:
        needs.append("merchant")           # 가맹점 모름 → 데스크가 묻거나 영수증이 채움
    return {
        "kind": "income" if is_income else "expense",
        "amount": amount,
        "method": method,
        "merchant": merchant,
        "category": _category_of(merchant, summary),
        "installment": bool(_INSTALL.search(summary)),
        "memo": summary.strip(),
        "source": "notification",
        "recurring": False,
        "complete": not needs,
        "needs": needs,
    }


def _day_range(target: date) -> Tuple[datetime, datetime]:
    return datetime.combine(target, dtime.min), datetime.combine(target, dtime.max)


# ── merge: 영수증 ↔ 카드알림 (출처가 다를 때 같은 결제로 합침) ──────
def _images_of(doc: Dict[str, Any]) -> List[str]:
    """그 항목에 붙은 영수증 이미지들(구 단일 receipt_image + 신 receipt_images 합쳐서)."""
    imgs = [x for x in (doc.get("receipt_images") or []) if x]
    one = doc.get("receipt_image")
    if one and one not in imgs:
        imgs.insert(0, one)
    return imgs


def _same_payment(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """같은 결제인가 — 금액·날짜는 호출부가 이미 맞춤. 여기선 '오합치기' 방지만.

    핵심 케이스: 영수증(merchant·품목 풍부) + 카드알림(결제수단 정확)이 같은 금액·날짜.
    출처가 다르면(하나는 receipt, 하나는 notification) 같은 결제로 본다.
    둘 다 알림이면 서로 다른 결제일 수 있어, 가맹점이 같을 때만 합친다.
    """
    sa, sb = a.get("source"), b.get("source")
    if "receipt" in (sa, sb) and sa != sb:
        return True
    am, bm = (a.get("merchant") or ""), (b.get("merchant") or "")
    return bool(am) and am == bm


def _parts_of(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """이 항목을 이루는 영수증 부분들 [{amount, rtype, key}]. 구 문서는 amount로 합성.

    rtype: 'card'(카드매출전표) | 'shop'(쇼핑몰·판매처, 기본). key: 영수증 식별(멱등 dedup용).
    """
    parts = doc.get("parts")
    if isinstance(parts, list) and parts:
        out = []
        for p in parts:
            a = int(p.get("amount") or 0)
            if a:
                out.append({"amount": a, "rtype": p.get("rtype") or "shop",
                            "merchant": p.get("merchant") or "",
                            "key": p.get("key") or f"{p.get('rtype') or 'shop'}-{a}"})
        return out
    a = doc.get("amount")
    if not a:
        return []
    rt = doc.get("rtype") or "shop"
    return [{"amount": int(a), "rtype": rt, "merchant": doc.get("merchant") or "",
             "key": doc.get("_id") or f"{rt}-{int(a)}"}]


def _recompute_amount(parts: List[Dict[str, Any]]):
    """부분 영수증들 → (대표금액, diff여부, 중복제거 parts).

    - **판매처가 여럿**이면 멀티셀러 한 주문 → 전부 **합산**(rtype 오분류에 강함).
    - 같은 판매처에 **카드전표**가 있으면 그게 진실 — 쇼핑몰 금액과 다르면 **diff**(직접 판독).
    - 그 외(쇼핑몰만) → 합산. 같은 영수증(key) 재처리는 멱등.
    """
    seen_k, seen_c, uniq = set(), set(), []
    for p in parts:
        k = p.get("key")
        c = (p.get("merchant"), p.get("amount"), p.get("rtype"))   # 내용 동일 = 같은 영수증
        if k in seen_k or c in seen_c:
            continue
        seen_k.add(k)
        seen_c.add(c)
        uniq.append(p)
    merchants = {p.get("merchant") for p in uniq if p.get("merchant")}
    if len(merchants) > 1:                     # 여러 판매처 = 멀티셀러 한 주문 → 합산
        return sum(p["amount"] for p in uniq), False, uniq
    shop = [p["amount"] for p in uniq if p.get("rtype") != "card"]
    card = [p["amount"] for p in uniq if p.get("rtype") == "card"]
    if card:
        card_total = max(card)
        return card_total, (bool(shop) and sum(shop) != card_total), uniq
    return sum(shop), False, uniq


def _merge_fields(existing: Dict[str, Any], incoming: Dict[str, Any],
                  by_approval: bool = False) -> Dict[str, Any]:
    """두 결제 합치기 — 빈 필드를 채운다. 영수증의 가맹점·품목·카테고리 우선.

    by_approval=True(승인번호 매칭): 같은 승인번호 영수증들을 한 건으로 묶음. 금액이 같으면
    그대로 1건, **다르면 diff=True**(쇼핑몰 vs 카드 금액 불일치) → 어드민서 직접 판독.
    False(금액+날짜): 같은 거래라 금액 유지.
    """
    out: Dict[str, Any] = {}
    if by_approval:
        amount, diff, uniq = _recompute_amount(_parts_of(existing) + _parts_of(incoming))
        out["parts"] = uniq
        out["amount_parts"] = [p["amount"] for p in uniq]
        out["amount"] = amount
        out["diff"] = diff
    for f in ("merchant", "category"):
        v = incoming.get(f) or existing.get(f)
        if v:
            out[f] = v
    items = (existing.get("items") or []) + [i for i in (incoming.get("items") or [])
                                             if i not in (existing.get("items") or [])]
    if items:
        out["items"] = items
    if not existing.get("method") and incoming.get("method"):
        out["method"] = incoming["method"]
    out["memo"] = existing.get("memo") or incoming.get("memo") or ""
    out["source"] = "merged"
    sids = list({*(existing.get("signal_ids") or []), *(incoming.get("signal_ids") or [])})
    if sids:
        out["signal_ids"] = sids
    if incoming.get("record_id"):
        out["record_id"] = incoming["record_id"]
    if incoming.get("approval_no") and not existing.get("approval_no"):
        out["approval_no"] = incoming["approval_no"]
    imgs = _images_of(existing)                            # 영수증 여러 장 한곳에(쇼핑몰+카드전표)
    for im in _images_of(incoming):
        if im not in imgs:
            imgs.append(im)
    if imgs:
        out["receipt_images"] = imgs
    # needs 재계산 — 합친 뒤에도 비어 있는 필수만
    merged_merchant = out.get("merchant") or existing.get("merchant")
    is_income = "income" in (existing.get("kind"), incoming.get("kind"))
    out["needs"] = [] if (is_income or merged_merchant) else ["merchant"]
    out["complete"] = not out["needs"]
    return out


def _merge_or_insert(doc: Dict[str, Any]) -> str:
    """같은 결제면 merge, 아니면 insert. 반환 'dup'|'merged'|'inserted'."""
    if db.ledger().find_one({"_id": doc["_id"]}):
        return "dup"                       # 같은 신호 재처리 — 멱등
    # 1) 승인번호 일치 — 가장 강력(쇼핑몰 영수증·카드 전표·카드알림이 다 같은 승인번호).
    #    날짜 무관(다른 시점 업로드도 한곳에 붙는다).
    appr = doc.get("approval_no")
    if appr:
        cand = db.ledger().find_one({"approval_no": appr, "_id": {"$ne": doc["_id"]}})
        if cand:
            db.ledger().update_one({"_id": cand["_id"]},
                                   {"$set": _merge_fields(cand, doc, by_approval=True)})
            return "merged"
    # 2) 금액 + 날짜(±1일) — 승인번호 없을 때 폴백.
    try:
        d0 = date.fromisoformat(doc["date"])
    except (ValueError, KeyError):
        db.ledger().insert_one(doc)
        return "inserted"
    near = [(d0 + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    for cand in db.ledger().find({
        "kind": doc.get("kind", "expense"),
        "amount": doc["amount"],
        "date": {"$in": near},
        "_id": {"$ne": doc["_id"]},
    }):
        if _same_payment(cand, doc):
            db.ledger().update_one({"_id": cand["_id"]},
                                   {"$set": _merge_fields(cand, doc)})
            return "merged"
    db.ledger().insert_one(doc)
    return "inserted"


def sync_from_briefs(target: Optional[date] = None) -> int:
    """그날 brief items → ledger upsert(멱등). 새로 담긴(insert/merge) 수 반환."""
    target = target or date.today()
    t0, t1 = _day_range(target)
    n = 0
    for b in db.signal_briefs().find({"ts": {"$gte": t0, "$lte": t1}}):
        ts = b.get("ts")
        for it in b.get("items", []):
            sender, summary = it.get("sender", ""), it.get("summary", "")
            p = parse_payment(sender, summary)
            if not p:
                continue
            sids = [s for s in (it.get("signal_ids") or []) if s]
            key = sids[0] if sids else f"{b['_id']}-{(summary or '')[:16]}"
            approval = ""                      # 승인번호 — 원본 신호 본문에서(요약엔 보통 없음)
            for sid in sids:
                sg = db.signals().find_one({"_id": sid}, {"body": 1})
                approval = _approval_of((sg or {}).get("body") or "") or _approval_of(summary)
                if approval:
                    break
            amts = _all_amounts(summary, f"{sender} {summary}") or [p["amount"]]
            for a in amts:                     # 한 알림에 'A원·B원 두 건'이면 건마다 따로
                pid = f"pay-{key}" if len(amts) == 1 else f"pay-{key}-{a}"
                doc = {"_id": pid, "date": target.isoformat(), "ts": ts,
                       "signal_ids": sids, **p, "amount": a}
                if len(amts) == 1 and approval:   # 여러 건이면 승인번호 어느 건인지 모호 → 생략
                    doc["approval_no"] = approval
                if _merge_or_insert(doc) in ("inserted", "merged"):
                    n += 1
    return n


def from_receipt(record_id: str, ts: Any, fields: Dict[str, Any]) -> str:
    """영수증 비전 추출 → ledger. fields={amount, merchant, items, method?, date?, kind?}.

    같은 금액·날짜의 카드알림이 있으면 merge(가맹점·품목 보강), 없으면 새 항목.
    반환 'merged'|'inserted'|'skip'(금액 없음).
    """
    amount = fields.get("amount")
    if not amount or int(amount) < 100:
        return "skip"
    d = fields.get("date")
    has_date = False
    try:
        if d:
            day = date.fromisoformat(d)
            has_date = True
        else:
            day = ts.date() if hasattr(ts, "date") else date.today()
    except (ValueError, TypeError):
        day = date.today()
    merchant = (fields.get("merchant") or "").strip()
    rtype = "card" if (fields.get("rtype") or "shop").strip().lower() == "card" else "shop"
    # 거래 시점 = 영수증 날짜(있으면) — 없을 때만 올린 시각(ts). 정오로 둬 같은 날 정렬 안정.
    entry_ts = (datetime.combine(day, dtime(12, 0)) if has_date
                else (ts if isinstance(ts, datetime) else datetime.combine(day, dtime.min)))
    doc = {
        "_id": f"pay-receipt-{record_id}",
        "date": day.isoformat(),
        "ts": entry_ts,
        "kind": fields.get("kind") or "expense",
        "amount": int(amount),
        "method": (fields.get("method") or "").strip(),
        "merchant": merchant,
        "category": _category_of(merchant, " ".join(fields.get("items") or []) or merchant),
        "items": [str(i).strip() for i in (fields.get("items") or []) if str(i).strip()][:30],
        "installment": False,
        "memo": (fields.get("memo") or merchant or "영수증").strip(),
        "source": "receipt",
        "recurring": False,
        "needs": [] if merchant else ["merchant"],
        "complete": bool(merchant),
        "record_id": record_id,
        "approval_no": str(fields.get("approval") or "").strip(),   # 승인번호 — 강력 매칭키
        "rtype": rtype,                                             # card 전표 / shop 쇼핑몰
        "parts": [{"amount": int(amount), "rtype": rtype, "merchant": merchant, "key": record_id}],
        "receipt_images": [im] if (im := (fields.get("image") or "").strip()) else [],
    }
    res = _merge_or_insert(doc)
    reconcile_card_notes(day)        # 그룹 총액과 같은 카드알림(확인필요) 있으면 흡수
    return res


def reconcile_card_notes(target: Optional[date] = None) -> int:
    """승인번호 없는 카드알림(확인필요)을 같은 금액·날짜의 영수증 그룹에 흡수.

    카드알림 총액 == 영수증 그룹 총액이면 같은 결제(영수증=그 알림의 상세). 그룹이 상세
    (가맹점·영수증)를 가지므로, 알림의 결제수단·신호·시간만 그룹에 넘기고 알림 entry 삭제 —
    이렇게 안 하면 같은 97,620원이 두 번 계상된다. 같은 금액·날짜에 그룹/알림이 각각 하나일
    때만(1:1 명확) 처리 — 오매칭 방지.
    """
    target = target or date.today()
    notes = list(db.ledger().find({
        "source": "notification", "approval_no": {"$in": [None, ""]},
        "date": {"$gte": (target - timedelta(days=35)).isoformat(),
                 "$lt": (target + timedelta(days=2)).isoformat()},
    }))
    fixed = 0
    for note in notes:
        amt, d0 = note.get("amount"), note.get("date")
        if not amt or not d0:
            continue
        near = [(date.fromisoformat(d0) + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
        groups = [g for g in db.ledger().find({
            "amount": amt, "date": {"$in": near}, "source": {"$in": ["receipt", "merged"]},
        }) if g.get("merchant") and (g.get("receipt_images") or g.get("approval_no"))]
        same_notes = [n for n in notes if n.get("amount") == amt and n.get("date") in near]
        if len(groups) != 1 or len(same_notes) != 1:     # 모호하면 건너뜀(수동 판독)
            continue
        g = groups[0]
        upd: Dict[str, Any] = {"source": "merged"}
        if not g.get("method") and note.get("method"):
            upd["method"] = note["method"]
        sids = list({*(g.get("signal_ids") or []), *(note.get("signal_ids") or [])})
        if sids:
            upd["signal_ids"] = sids
        if note.get("ts"):                               # 알림의 실제 결제 시각 반영
            upd["ts"] = note["ts"]
        db.ledger().update_one({"_id": g["_id"]}, {"$set": upd})
        db.ledger().delete_one({"_id": note["_id"]})
        fixed += 1
    return fixed


# ── 조회 ─────────────────────────────────────────────────────────
def _row_view(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["_id"],
        "kind": r.get("kind", "expense"),
        "amount": r.get("amount", 0),
        "method": r.get("method") or r.get("card", ""),   # 구 문서 card 호환
        "merchant": r.get("merchant", ""),
        "category": r.get("category", ""),
        "items": r.get("items", []),
        "installment": bool(r.get("installment")),
        "recurring": bool(r.get("recurring")),
        "memo": r.get("memo", ""),
        "complete": bool(r.get("complete", True)),
        "needs": r.get("needs", []),
        "source": r.get("source", "notification"),
        "receipt_images": _images_of(r),               # 여러 장 — /photos/{경로}로 열람
        "approval_no": r.get("approval_no", ""),
        "amount_parts": [int(x) for x in (r.get("amount_parts") or []) if x],  # 승인번호 묶음 금액들
        "diff": bool(r.get("diff")),                   # 금액 불일치(직접 판독 필요)
        "ts": r["ts"].isoformat() if isinstance(r.get("ts"), datetime) else None,
    }


def today(target: Optional[date] = None) -> Dict[str, Any]:
    """그날 가계부 — 수입/지출 합·건수·항목(시간순)."""
    target = target or date.today()
    rows = list(db.ledger().find({"date": target.isoformat()}).sort("ts", 1))
    expense = sum(int(r.get("amount", 0)) for r in rows if r.get("kind", "expense") == "expense")
    income = sum(int(r.get("amount", 0)) for r in rows if r.get("kind") == "income")
    return {
        "date": target.isoformat(),
        "total": expense,            # 구앱 호환(지출 합)
        "expense": expense,
        "income": income,
        "net": income - expense,
        "count": len(rows),
        "items": [_row_view(r) for r in rows],
    }


def entries(period: str = "month", target: Optional[date] = None) -> List[Dict[str, Any]]:
    """기간 전체 거래내역(시간순) — 어드민 장부/대차대조표용."""
    target = target or date.today()
    period = "week" if period == "week" else "month"
    start, end = _period_range(period, target)
    rows = list(db.ledger().find(
        {"date": {"$gte": start.isoformat(), "$lt": end.isoformat()}}).sort("ts", 1))
    return [_row_view(r) for r in rows]


def incomplete(within_days: int = 14, limit: int = 20) -> List[Dict[str, Any]]:
    """정보 부족(needs) 지출 — 데스크 '지출내역 확인필요'용."""
    since = (date.today() - timedelta(days=within_days)).isoformat()
    rows = db.ledger().find(
        {"needs": {"$exists": True, "$ne": []}, "date": {"$gte": since}}
    ).sort("ts", -1).limit(limit)
    return [_row_view(r) for r in rows]


def set_fields(pay_id: str, fields: Dict[str, Any]) -> bool:
    """확인필요 항목 채우기(데스크) — merchant·category·method 등. needs/complete 재계산."""
    r = db.ledger().find_one({"_id": pay_id})
    if not r:
        return False
    upd = {k: v for k, v in (fields or {}).items()
           if k in ("merchant", "category", "method", "amount", "kind", "memo") and v not in (None, "")}
    if not upd:
        return False
    merged = {**r, **upd}
    needs = [] if (merged.get("kind") == "income" or merged.get("merchant")) else ["merchant"]
    upd["needs"] = needs
    upd["complete"] = not needs
    db.ledger().update_one({"_id": pay_id}, {"$set": upd})
    return True


def resolve_diff(pay_id: str, amount: int) -> bool:
    """금액 불일치(diff) 판독 — 사용자가 고른 금액으로 확정하고 diff 해제."""
    try:
        amt = int(amount)
    except (TypeError, ValueError):
        return False
    if amt <= 0 or not db.ledger().find_one({"_id": pay_id}):
        return False
    db.ledger().update_one({"_id": pay_id},
                           {"$set": {"amount": amt, "amount_parts": [amt], "diff": False,
                                     "parts": [{"amount": amt, "rtype": "card", "key": "resolved"}]}})
    return True


def attach_receipt(pay_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """**특정 항목**에 영수증 붙이기 — 자동 매칭 없이, 내가 고른 그 항목을 영수증 추출값으로 채움.

    가맹점·품목·카테고리·이미지를 채우고(금액은 그 항목 것 유지), needs/complete 재계산.
    fields: {merchant?, items?, method?, image?}.
    """
    r = db.ledger().find_one({"_id": pay_id})
    if not r:
        return None
    upd: Dict[str, Any] = {}
    merchant = (fields.get("merchant") or "").strip()
    if merchant:
        upd["merchant"] = merchant
    items = [str(i).strip() for i in (fields.get("items") or []) if str(i).strip()][:30]
    if items:
        upd["items"] = items
    if fields.get("method") and not r.get("method"):
        upd["method"] = str(fields["method"]).strip()
    if fields.get("approval") and not r.get("approval_no"):
        upd["approval_no"] = str(fields["approval"]).strip()
    if fields.get("image"):
        imgs = _images_of(r)
        im = str(fields["image"]).strip()
        if im and im not in imgs:
            imgs.append(im)                                # 여러 장 누적(쇼핑몰+카드전표)
        upd["receipt_images"] = imgs
    merged_merchant = upd.get("merchant") or r.get("merchant")
    if merged_merchant and not r.get("category"):
        upd["category"] = _category_of(merged_merchant, " ".join(items) or merged_merchant)
    is_income = r.get("kind") == "income"
    upd["needs"] = [] if (is_income or merged_merchant) else ["merchant"]
    upd["complete"] = not upd["needs"]
    db.ledger().update_one({"_id": pay_id}, {"$set": upd})
    return _row_view({**r, **upd})


def remove(pay_id: str) -> bool:
    """오기록 삭제 (오탐 제거·수동 정리용)."""
    return db.ledger().delete_one({"_id": pay_id}).deleted_count > 0


# ── 반복결제(구독) 추정 ──────────────────────────────────────────
def recurring(before: Optional[date] = None, lookback_days: int = 95) -> List[Dict[str, Any]]:
    """가맹점이 다른 달에 비슷한 금액으로 반복되면 구독·정기결제로 추정.

    가맹점이 채워진 지출에서만(알림은 가맹점 비는 경우 많음 → 영수증·확인으로 채울수록 정확).
    """
    before = before or date.today()
    since = (before - timedelta(days=lookback_days)).isoformat()
    bucket: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for r in db.ledger().find({"kind": "expense", "date": {"$gte": since},
                               "merchant": {"$nin": ["", None]}}):
        bucket[r["merchant"]].append((r["date"][:7], int(r.get("amount", 0))))
    out: List[Dict[str, Any]] = []
    for merchant, lst in bucket.items():
        months = {mo for mo, _ in lst}
        if len(months) < 2:
            continue
        amt = Counter(a for _, a in lst).most_common(1)[0][0]
        out.append({"merchant": merchant, "amount": amt, "months": len(months)})
    out.sort(key=lambda x: -x["amount"])
    return out


# ── 결산 (주/월) — 대차대조표 형태 ──────────────────────────────
def _period_range(period: str, target: date) -> Tuple[date, date]:
    if period == "week":
        start = target - timedelta(days=target.weekday())   # 그 주 월요일
        return start, start + timedelta(days=7)
    start = target.replace(day=1)                            # 그 달 1일
    return start, (start + timedelta(days=32)).replace(day=1)


def settlement(period: str = "month", target: Optional[date] = None) -> Dict[str, Any]:
    """주/월 결산 — 수입·지출·순액 + 카테고리/결제수단/상위가맹점 + 반복·미완. 대차대조표용."""
    target = target or date.today()
    period = "week" if period == "week" else "month"
    start, end = _period_range(period, target)
    rows = list(db.ledger().find(
        {"date": {"$gte": start.isoformat(), "$lt": end.isoformat()}}).sort("ts", 1))
    income = sum(int(r.get("amount", 0)) for r in rows if r.get("kind") == "income")
    expense = sum(int(r.get("amount", 0)) for r in rows if r.get("kind", "expense") == "expense")
    by_cat: Counter = Counter()
    by_method: Counter = Counter()
    by_merchant: Counter = Counter()
    for r in rows:
        if r.get("kind", "expense") != "expense":
            continue
        amt = int(r.get("amount", 0))
        by_cat[r.get("category") or "미분류"] += amt
        by_method[r.get("method") or r.get("card") or "기타"] += amt
        if r.get("merchant"):
            by_merchant[r["merchant"]] += amt
    return {
        "period": period,
        "start": start.isoformat(),
        "end": (end - timedelta(days=1)).isoformat(),
        "income": income,
        "expense": expense,
        "net": income - expense,
        "count": len(rows),
        "by_category": [{"name": k, "amount": v} for k, v in by_cat.most_common()],
        "by_method": [{"name": k, "amount": v} for k, v in by_method.most_common()],
        "top_merchants": [{"name": k, "amount": v} for k, v in by_merchant.most_common(8)],
        "recurring": recurring(end),
        "incomplete": sum(1 for r in rows if r.get("needs")),
    }


def settlement_line(period: str = "week", target: Optional[date] = None) -> str:
    """동반자(베르)가 일기·발행물에서 쓸 한두 줄 결산 요약. 자료 없으면 ''."""
    s = settlement(period, target)
    if s["count"] == 0:
        return ""
    label = "이번 주" if period == "week" else "이번 달"
    parts = [f"{label} 지출 {s['expense']:,}원"]
    if s["income"]:
        parts.append(f"수입 {s['income']:,}원(순 {s['net']:,}원)")
    top = s["by_category"][:3]
    if top:
        parts.append("주로 " + ", ".join(f"{c['name']} {c['amount']:,}원" for c in top))
    if s["recurring"]:
        parts.append(f"정기결제 {len(s['recurring'])}건")
    return " · ".join(parts) + "."


def settlement_material(period: str = "week", target: Optional[date] = None) -> str:
    """주/월 회고 재료용 결산 텍스트 블록(여러 줄). 자료 없으면 ''."""
    s = settlement(period, target)
    if s["count"] == 0:
        return ""
    lines = [f"수입 {s['income']:,}원 · 지출 {s['expense']:,}원 · 순 {s['net']:,}원 ({s['count']}건)"]
    if s["by_category"]:
        lines.append("분류: " + ", ".join(
            f"{c['name']} {c['amount']:,}" for c in s["by_category"][:6]))
    if s["by_method"]:
        lines.append("결제수단: " + ", ".join(
            f"{m['name']} {m['amount']:,}" for m in s["by_method"][:5]))
    if s["top_merchants"]:
        lines.append("많이 쓴 곳: " + ", ".join(
            f"{m['name']} {m['amount']:,}" for m in s["top_merchants"][:5]))
    if s["recurring"]:
        lines.append("정기결제(추정): " + ", ".join(
            f"{r['merchant']} {r['amount']:,}" for r in s["recurring"][:6]))
    return "\n".join(lines)
