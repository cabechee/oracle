"""발행물 — 조간(아침)·석간(저녁). 베르가 cron으로 하루를 열고 닫는다.

자정 일기(journals)가 '어제 회고'라면, 이건 '오늘의 시작/마무리':
- 조간: 어젯밤 수면 + 밤새 신호 + 어제 한 줄 + On This Day + 오늘 일정(캘린더, 추후) → 베르 합성
- 석간: 오늘 기록 흐름 + 펜딩 환기 → 한 줄 권유

briefings 컬렉션(_id=morning-YYYY-MM-DD / evening-YYYY-MM-DD)에 저장. 앱이 폴링해
새 발행물이면 푸시 + 홈 표지 카드. 미요약 신호는 먼저 강제 요약해 밤샘분을 포함.
"""

import json
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional

import db
import signals as signals_mod
from agent import llm, personas
from config import task_alias


def _alias() -> str:
    # 발행물도 메인(베르). digest 알리아스 재사용(없으면 Nest 첫 모델).
    return (task_alias("daily_digest") or task_alias("chat")
            or llm.default_alias() or "")


def _day_range(d: date):
    return datetime.combine(d, dtime.min), datetime.combine(d, dtime.max)


def _yesterday_journal_line(today: date) -> str:
    j = db.journals().find_one({"_id": f"day-{(today - timedelta(days=1)).isoformat()}"})
    if not j:
        return ""
    for ln in (j.get("text") or "").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            return s[:200]
    return ""


def _on_this_day(today: date) -> List[str]:
    out = []
    for label, d in (("작년 오늘", today.replace(year=today.year - 1)),
                     ("한 달 전", today - timedelta(days=30))):
        r0, r1 = _day_range(d)
        rec = db.records().find_one({"ts": {"$gte": r0, "$lte": r1}}, sort=[("ts", 1)])
        if rec:
            uc = (rec.get("user_comment") or "").strip()
            ins = ((rec.get("insight") or {}).get("text") or "").strip()
            line = uc or ins
            if line:
                out.append(f"{label}: {line[:80]}")
    return out


def run_morning(target: Optional[date] = None) -> Dict[str, Any]:
    """조간 합성 — 어젯밤 수면 + 밤새 신호 + 어제 한 줄 + On This Day."""
    today = target or date.today()
    # 밤새 신호 먼저 요약(미요약분 포함) — 아침에 다 모아 보여주기
    try:
        signals_mod.rebrief_pending()
    except Exception:
        pass

    parts: List[str] = []
    m = db.metrics().find_one({"_id": today.isoformat()})
    if m and m.get("sleep_min"):
        parts.append(f"[어젯밤 수면] {m['sleep_min'] // 60}시간 {m['sleep_min'] % 60}분")

    # 최근 신호 요약 2건(밤새~아침)
    briefs = list(db.signal_briefs().find().sort("ts", -1).limit(2))
    sig = [b.get("summary", "") for b in briefs if b.get("summary")]
    if sig:
        parts.append(
            f"[밤새 온 연락 — {personas.SENDER_ATTRIBUTION_SHORT}]\n" + "\n".join(sig))

    line = _yesterday_journal_line(today)
    if line:
        parts.append(f"[어제 하루] {line}")

    otd = _on_this_day(today)
    if otd:
        parts.append("[그날의 오늘]\n" + "\n".join(otd))

    return _compose("morning", today, parts, personas.morning_system())


def run_evening(target: Optional[date] = None) -> Dict[str, Any]:
    """석간 합성 — 오늘 기록 흐름 + 펜딩 환기 + 한 줄 권유."""
    today = target or date.today()
    t0, t1 = _day_range(today)
    recs = list(db.records().find({"ts": {"$gte": t0, "$lte": t1}}).sort("ts", 1))

    parts: List[str] = [f"[오늘 기록] {len(recs)}건"]
    briefs = []
    for r in recs:
        uc = (r.get("user_comment") or "").strip()
        ins = ((r.get("insight") or {}).get("text") or "").strip()
        if uc or ins:
            briefs.append(f"- {(uc or ins)[:60]}")
    if briefs:
        parts.append("\n".join(briefs[:12]))

    try:
        import ledger as ledger_mod
        pays = [it for it in ledger_mod.today(today).get("items", [])
                if it.get("kind") != "income"]
    except Exception:
        pays = []
    if pays:
        parts.append(
            f"[오늘 아빠가 결제한 내역 — {personas.WHO_PAID_SHORT}]\n"
            + "\n".join(f"- {it.get('merchant') or it.get('memo') or '결제'} "
                        f"{it.get('amount', 0):,}원" for it in pays))

    return _compose("evening", today, parts, personas.evening_system())


def _compose(kind: str, target: date, material: List[str],
             system: str) -> Dict[str, Any]:
    alias = _alias()
    if not alias:
        return {"ok": False, "reason": "alias 미설정"}
    body = "\n\n".join(material)
    prompt = f"[오늘 {target.isoformat()}]\n\n{body}\n\n위 재료로 작성해주세요."
    try:
        r = llm.call_retry(alias, prompt, system=system)
        text = (r.get("text") or "").strip()
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    if not text:
        return {"ok": False, "reason": "빈 응답"}
    bid = f"{kind}-{target.isoformat()}"
    db.briefings().update_one(
        {"_id": bid},
        {"$set": {"kind": kind, "date": target.isoformat(),
                  "text": text, "ts": datetime.now()}},
        upsert=True)
    return {"ok": True, "id": bid, "kind": kind, "preview": text[:120]}


# ── 조회 (앱) ───────────────────────────────────────────────

def latest(kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    flt = {"kind": kind} if kind else {}
    b = db.briefings().find_one(flt, sort=[("ts", -1)])
    if not b:
        return None
    return {"id": b["_id"], "kind": b.get("kind"), "date": b.get("date"),
            "text": b.get("text", ""),
            "ts": b["ts"].isoformat() if isinstance(b.get("ts"), datetime) else None}


def recent(limit: int = 30) -> List[Dict[str, Any]]:
    out = []
    for b in db.briefings().find().sort("ts", -1).limit(limit):
        out.append({"id": b["_id"], "kind": b.get("kind"), "date": b.get("date"),
                    "text": b.get("text", ""),
                    "ts": b["ts"].isoformat() if isinstance(b.get("ts"), datetime) else None})
    return out
