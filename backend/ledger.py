"""가계부 — 결제 알림에서 지출을 뽑아 누적하는 스마트 액션.

대신 읽어드림이 모은 신호 중 '결제/승인/출금'은 그냥 읽고 흘리는 대신 가계부
항목으로 떨군다. 신호 id 기준 멱등(같은 결제 두 번 안 쌓임). 코드 정규식 1차 —
LLM 분류(items)가 이미 한 줄 요약을 만들어 두므로 거기서 금액·결제수단만 뽑는다.
"""

import re
from datetime import date, datetime, time as dtime
from typing import Any, Dict, List, Optional

import db

_AMOUNT = re.compile(r"([\d][\d,]{1,})\s*원")
_APPROVE = re.compile(r"승인|결제|출금|이체|구매|결제완료|납부")
# 결제수단/기관 힌트 — 적립·쿠폰 등 비지출 오탐 방지용
_PAYMENT_HINT = re.compile(
    r"카드|페이|뱅크|은행|카카오|토스|현대|삼성|국민|신한|롯데|우리|하나|BC|페이코|"
    r"체크|신용|일시불|할부|계좌")
# 명백한 비지출(적립·쿠폰·환급·광고)이면 제외
_NON_SPEND = re.compile(r"적립|쿠폰|환급|할인|광고|이벤트|당첨|포인트")


def parse_payment(sender: str, summary: str) -> Optional[Dict[str, Any]]:
    """신호 한 줄에서 결제(지출)를 추출. 아니면 None.

    예) ("현대카드", "the Pink로 19,000원 일시불 승인됨") → {amount:19000, ...}
    """
    text = f"{sender} {summary}"
    if not _APPROVE.search(text):
        return None
    if _NON_SPEND.search(text):
        return None
    m = _AMOUNT.search(summary) or _AMOUNT.search(text)
    if not m:
        return None
    amount = int(m.group(1).replace(",", ""))
    if amount < 100:                       # 너무 작으면 노이즈
        return None
    if not _PAYMENT_HINT.search(text):     # 결제수단 힌트 없으면 보류
        return None
    return {
        "amount": amount,
        "card": sender.strip(),
        "installment": bool(re.search(r"할부", summary)),
        "memo": summary.strip(),
    }


def _day_range(target: date):
    return datetime.combine(target, dtime.min), datetime.combine(target, dtime.max)


def sync_from_briefs(target: Optional[date] = None) -> int:
    """그날 brief items에서 결제를 ledger에 upsert (signal_id 기준 멱등). 새로 담긴 수 반환."""
    target = target or date.today()
    t0, t1 = _day_range(target)
    n = 0
    for b in db.signal_briefs().find({"ts": {"$gte": t0, "$lte": t1}}):
        ts = b.get("ts")
        for it in b.get("items", []):
            p = parse_payment(it.get("sender", ""), it.get("summary", ""))
            if not p:
                continue
            sids = it.get("signal_ids") or []
            key = sids[0] if sids else f"{b['_id']}-{(it.get('summary') or '')[:16]}"
            doc = {
                "_id": f"pay-{key}",
                "date": target.isoformat(),
                "ts": ts,
                "signal_ids": sids,
                **p,
            }
            res = db.ledger().update_one(
                {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
            if res.upserted_id is not None:
                n += 1
    return n


def today(target: Optional[date] = None) -> Dict[str, Any]:
    """그날 가계부 — 총액·건수·항목(시간순)."""
    target = target or date.today()
    rows = list(db.ledger().find({"date": target.isoformat()}).sort("ts", 1))
    total = sum(int(r.get("amount", 0)) for r in rows)
    return {
        "date": target.isoformat(),
        "total": total,
        "count": len(rows),
        "items": [
            {
                "id": r["_id"],
                "amount": r.get("amount", 0),
                "card": r.get("card", ""),
                "installment": bool(r.get("installment")),
                "memo": r.get("memo", ""),
                "ts": r["ts"].isoformat() if isinstance(r.get("ts"), datetime) else None,
            }
            for r in rows
        ],
    }


def remove(pay_id: str) -> bool:
    """오기록 삭제 (오탐 제거용)."""
    return db.ledger().delete_one({"_id": pay_id}).deleted_count > 0
