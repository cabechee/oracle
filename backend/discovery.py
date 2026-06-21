"""발견 — 하루 1회 메뉴별로 LLM이 그 영역 기록을 들여다보고 '깨달음·느낀 점·패턴' 한 줄.

어드민 각 메뉴 상단에 quote로 뜨고(확인 누르면 그날은 닫힘), 따로 '발견' 로그에 쌓인다.
판단·훈수가 아니라 사용자가 스스로 알아차리게 돕는 담백한 관찰. 자정 배치가 생성한다.
"""

import datetime
from typing import Any, Dict, List, Optional

import db

# 메뉴키 → 라벨 (데이터 있는 메뉴만 — 설정 메뉴는 발견 대상 아님)
MENUS: Dict[str, str] = {
    "home": "홈", "ledger": "가계부", "calendar": "캘린더", "records": "캡처",
    "signals": "신호", "journals": "저널", "conversations": "대화", "collected": "활동 로그",
}

_SYSTEM = (
    "너는 사용자의 기록을 가만히 들여다보고 '깨달음·느낀 점·반복되는 패턴'을 한두 문장으로 짚어주는 관찰자야.\n"
    "훈수·평가·조언이 아니라, 사용자가 스스로 알아차리게 돕는 담백하고 따뜻한 한 줄.\n"
    "데이터에 실제로 있는 것만. 지어내지 말고, 특별히 짚을 게 없으면 정확히 '없음'만 출력."
)


def _records_text(limit: int = 12) -> str:
    out = []
    for r in db.records().find().sort("ts", -1).limit(limit):
        cap = (r.get("user_comment") or "").strip()
        ins = ((r.get("insight") or {}).get("text") or "").strip()
        sc = ((r.get("analysis") or {}).get("scene") or "").strip()
        line = cap or sc or ins[:60]
        if line:
            out.append("- " + line[:90])
    return "\n".join(out)


def _context(menu: str) -> Optional[str]:
    """메뉴별 최근 데이터 요약 텍스트. 볼 게 없으면 None."""
    try:
        if menu == "ledger":
            import ledger
            return ledger.settlement_material("month") or None
        if menu == "calendar":
            import gcal
            lines = gcal.day_lines() + [f"{e.get('title','')}" for e in gcal.upcoming(days=10)]
            t = "\n".join(x for x in lines if x)
            return t or None
        if menu == "records":
            return _records_text(14) or None
        if menu == "signals":
            import signals
            rec = signals.recent(brief_limit=20, signal_limit=0).get("briefs", [])
            t = "\n".join("- " + (b.get("summary") or "")[:90] for b in rec if b.get("summary"))
            return t or None
        if menu == "journals":
            js = list(db.journals().find().sort("ts", -1).limit(3))
            t = "\n\n".join((j.get("text") or "")[:600] for j in js if j.get("text"))
            return t or None
        if menu == "conversations":
            cs = list(db.conversations().find().sort("ts", -1).limit(20))
            t = "\n".join(f"- {c.get('role','')}: {(c.get('text') or '')[:80]}" for c in reversed(cs) if c.get("text"))
            return t or None
        if menu == "collected":
            import visits
            vs = visits.recent(20)
            t = "\n".join(f"- {v.get('name') or '미지정'} {v.get('minutes',0)}분" for v in vs)
            return t or None
        if menu == "home":
            parts = [_records_text(8)]
            try:
                import ledger
                parts.append(ledger.settlement_line("week") or "")
            except Exception:
                pass
            t = "\n".join(p for p in parts if p)
            return t or None
    except Exception as e:
        print(f"[discovery] {menu} 컨텍스트 실패: {e}", flush=True)
    return None


def generate_all(target: Optional[datetime.date] = None) -> Dict[str, Any]:
    """자정 배치 — 메뉴마다 발견 한 줄 생성(있으면). 같은 날 재실행은 덮어씀."""
    from agent import llm
    import ingest
    target = target or datetime.date.today()
    alias = ingest._resolve_alias("discovery", None, prefer_vision=False, fallback_key="insight")
    made = []
    for menu, label in MENUS.items():
        ctx = _context(menu)
        if not ctx or len(ctx) < 12:
            continue
        try:
            r = llm.call(alias, f"[{label}] 최근 기록이야:\n{ctx}\n\n여기서 발견한 한 줄(없으면 '없음'):", system=_SYSTEM)
            text = (r.get("text") or "").strip()
        except Exception as e:
            print(f"[discovery] {menu} LLM 실패: {e}", flush=True)
            continue
        if not text or text.replace(".", "").strip() == "없음" or len(text) < 6:
            continue
        db.discoveries().update_one(
            {"_id": f"{menu}-{target.isoformat()}"},
            {"$set": {"menu": menu, "date": target.isoformat(), "text": text,
                      "created": datetime.datetime.now(), "dismissed": False}}, upsert=True)
        made.append(menu)
    return {"generated": len(made), "menus": made}


def today(menu: str, target: Optional[datetime.date] = None) -> Optional[Dict[str, Any]]:
    """그 메뉴의 오늘 발견(확인 안 한 것). 없으면 None."""
    target = target or datetime.date.today()
    d = db.discoveries().find_one({"_id": f"{menu}-{target.isoformat()}", "dismissed": {"$ne": True}})
    return {"menu": menu, "date": d["date"], "text": d["text"]} if d else None


def dismiss(menu: str, target: Optional[datetime.date] = None) -> bool:
    """오늘 그 메뉴 발견 닫기(그날은 다시 안 뜸)."""
    target = target or datetime.date.today()
    db.discoveries().update_one({"_id": f"{menu}-{target.isoformat()}"}, {"$set": {"dismissed": True}})
    return True


def log(limit: int = 80) -> List[Dict[str, Any]]:
    """발견 로그 — 최신순(어드민 '발견' 메뉴)."""
    out = []
    for d in db.discoveries().find().sort("date", -1).limit(limit):
        out.append({"menu": d.get("menu"), "label": MENUS.get(d.get("menu"), d.get("menu")),
                    "date": d.get("date"), "text": d.get("text"), "dismissed": bool(d.get("dismissed"))})
    return out
