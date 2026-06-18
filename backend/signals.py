"""수동 신호 평면 — SMS·부재중 전화 동기화 + 30분 주기 요약.

record(능동 캡처)와 구분되는 수동 스트림. 앱 콜렉터(WorkManager, 30분)가
미읽음 SMS + 부재중 통화를 POST /signals/sync로 보내면:
  1. 원본을 signals 컬렉션에 저장 (결정적 id로 dedupe — 겹치는 윈도우 무해)
  2. 이번에 처음 본 것만 모아 로컬 LLM으로 요약 (새 게 없으면 요약 없음 → 알림 없음)
  3. 요약을 signal_briefs에 남기고 앱에 반환 → 앱이 로컬 알림으로 표시

프라이버시 (사용자 결정 2026-06-11):
- SMS 본문은 로컬 LLM(ORACLE_SIGNALS, 예: qwen-vlm@milk)에서만 처리. 클라우드 금지.
- 인증번호/OTP 문자는 본문을 저장·요약 모두에서 제외 (redact).
"""

import collections
import hashlib
import json
import re
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional

import db
from agent import llm
from config import task_alias

# 신호 분류 카테고리 (우선순위 순) — 문자·부재중·푸시 알림 공통
SIGNAL_CATEGORIES = ["action_needed", "attention", "acquaintance", "low", "spam"]

# 부재중 전화 신선도 — 이보다 오래된 미요약 부재중은 '회신 필요'로 안 띄우고 age-out.
_CALL_FRESH = timedelta(hours=48)

SIGNALS_SYSTEM = """당신은 유저의 문자·부재중·앱 알림을 분류하고 요약하는 비서입니다.
각 신호를 정확히 하나의 카테고리로 분류하고, 핵심을 한 줄로 요약하세요.

카테고리:
- action_needed: 회신·결제·예약확인·기한 등 당장 행동이 필요한 것
- attention: 거래내역·배송·일정 등 알아둘 것 (급하진 않음)
- acquaintance: 지인·개인이 보낸 연락 (개인 번호 010 등에서 온 대화체)
- low: 시스템·일반 알림 (신경 안 써도 됨)
- spam: 광고·홍보·마케팅

규칙:
- 각 입력 신호의 "id"를 결과 항목의 signal_ids에 그대로 넣어 어느 신호인지 매칭하세요.
- 비슷한 광고 여러 개는 한 항목으로 묶어도 됩니다(signal_ids에 다 넣기).
- 지인 판단: 개인 번호의 대화체면 acquaintance, 기관·번호식별자(1588 등)면 아님.
- 없는 내용을 지어내지 말 것.
- ★summary는 '무엇을 말했는지·뭐가 왔는지'를 담은 구체적 한 줄. **'~에 대한 대화입니다'·'~ 관련 알림입니다' 같은 메타 묘사는 절대 금지** — 본문 핵심을 그대로 살려 써라.
  예) "저녁 메뉴와 식사 여부에 대한 대화" → "저녁 뭐 먹을지 묻고 배고프다고 함"
      "특정 내용에 대해 궁금하다는 연락" → "이 가게 궁금하다며 가보고 싶어함"
      "리워드 관련 알림" → "리워드 3천원 적립됨"
  짧은 메시지는 거의 원문대로, 한 발신인이 여러 줄 보냈으면 핵심만 추리되 뭉뚱그리지 말 것.
  어미도 '~함/~왔음/~라고 함/~준대' 처럼 짧은 사실 종결로 쓰고, '~하는 대화입니다·~에 관한 대화입니다·~ 알림입니다·~ 보고서입니다' 같은 격식·메타 어미는 쓰지 마라. (나쁜 예 "빙수 모임 가능 여부를 묻는 대화입니다" → 좋은 예 "빙수 모임 하자고 물어봄")
- [유저 피드백]에 "부정확"으로 표시된 발신인이 있으면 분류를 재고하세요.
- ★시각: "시각"에 날짜가 함께 있으면(예 "6/7 08:02") 오늘이 아닌 지난 신호다 — 요약에 **그 날짜를 반드시 넣어라**(예 "6/7 부재중, 회신 필요"). 날짜 없이 시각만 있으면 오늘 것이다. 오래된 부재중을 오늘 일처럼 쓰지 말 것.

아래 JSON 하나만 출력(JSON 외 텍스트 금지):
{"items": [{"category": "action_needed", "sender": "보낸이", "summary": "한 줄 요약", "signal_ids": ["sig-..."]}]}"""

# 인증번호/OTP — 키워드 + 4~8자리 숫자 동시 등장 시 본문 redact
_OTP_KEYWORD = re.compile(r"인증\s*번호|인증코드|승인번호|verification\s*code|\bOTP\b|일회용\s*비밀번호", re.I)
_OTP_DIGITS = re.compile(r"\b\d{4,8}\b")
_OTP_REDACTED = "[인증번호 문자 — 본문 생략]"

# 알림·문자 본문에 보이는 링크 — 딥링크(PendingIntent)는 못 가져오지만 본문 URL은 추출 가능.
_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")


def _extract_urls(text: str, limit: int = 3) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    for m in _URL_RE.findall(text):
        u = m.rstrip(".,)")
        if u and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def _is_otp(body: str) -> bool:
    return bool(_OTP_KEYWORD.search(body)) and bool(_OTP_DIGITS.search(body))


def _to_dt(ts_ms: Any) -> Optional[datetime]:
    """epoch millis → datetime (로컬). 이상값은 None."""
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000.0)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _signal_id(kind: str, sender: str, ts_ms: Any, body: str) -> str:
    """결정적 id — 같은 신호가 다시 와도 upsert로 dedupe."""
    raw = f"{kind}|{sender}|{ts_ms}|{body[:60]}"
    return f"sig-{hashlib.sha1(raw.encode()).hexdigest()[:14]}"


_KIND_LABEL = {"sms": "문자", "missed_call": "부재중 전화", "notification": "앱 알림"}


def _brief_prompt(items: List[Dict[str, Any]], now: Optional[datetime] = None) -> str:
    today = (now or datetime.now()).date()
    rows = []
    for it in items:
        ts = it.get("ts")
        if isinstance(ts, datetime):
            # 오늘이면 시각만, 지난 날이면 날짜까지 — 오래된 신호를 오늘 것처럼 요약하지 않게.
            when = ts.strftime("%H:%M") if ts.date() == today \
                else ts.strftime("%-m/%-d %H:%M")
        else:
            when = ""
        rows.append({
            "id": it["_id"],
            "종류": _KIND_LABEL.get(it.get("kind"), "신호"),
            "앱": it.get("app") or "",                    # 푸시 알림이면 출처 앱
            "보낸이": it.get("sender") or "(알 수 없음)",
            "시각": when,
            "내용": it.get("body") or "",
        })
    hints = _feedback_hints()
    fb = f"\n\n[유저 피드백 — 분류가 부정확했던 발신인]\n{json.dumps(hints, ensure_ascii=False)}" if hints else ""
    return (
        f"[새로 온 신호 {len(rows)}건]\n"
        + json.dumps(rows, ensure_ascii=False, indent=1)
        + fb
        + "\n\n위 신호들을 분류·요약해 지정된 JSON으로 출력하세요."
    )


def _feedback_hints() -> List[str]:
    """과거에 '부정확'으로 표시됐던 항목의 발신인 목록 — 재분류 힌트."""
    senders = set()
    for b in db.signal_briefs().find({"items.feedback": "inaccurate"}, {"items": 1}):
        for it in b.get("items", []):
            if it.get("feedback") == "inaccurate" and it.get("sender"):
                senders.add(it["sender"])
    return sorted(senders)[:20]


def sync(sms: List[Dict[str, Any]], calls: List[Dict[str, Any]],
         notifications: Optional[List[Dict[str, Any]]] = None,
         source: Optional[str] = None) -> Dict[str, Any]:
    """동기화 1회 — 저장(dedupe) + 미요약분 일괄 요약.

    요약 성공 시에만 briefed 마킹 → 로컬 LLM이 꺼져 있던 동안 온 신호도
    다음 주기에 자연 재시도 (48h 지나면 age-out). OTP는 요약 대상에서 제외.
    source: 보낸 기기/클라이언트(수집기·폰 등) — 신호에 provenance로 기록(graceful).
    반환: {new_sms, new_calls, sms_count, call_count, summary}
    (*_count = 이번 brief에 실제 포함된 건수 — 알림 표기용).
    """
    now = datetime.now()
    new_sms = new_calls = new_notif = 0

    for m in sms or []:
        sender = str(m.get("from") or "").strip()
        body = str(m.get("body") or "").strip()
        if not sender and not body:
            continue
        otp = _is_otp(body)
        doc = {
            "_id": _signal_id("sms", sender, m.get("ts"), body),
            "kind": "sms",
            "sender": sender,
            "body": _OTP_REDACTED if otp else body,
            "otp": otp,
            "briefed": otp,            # OTP는 요약 안 함 — 시작부터 처리됨 취급
            "ts": _to_dt(m.get("ts")) or now,
            "source": source,
            "synced_at": now,
        }
        res = db.signals().update_one(
            {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        if res.upserted_id is not None:
            new_sms += 1

    for c in calls or []:
        sender = str(c.get("from") or "").strip()
        doc = {
            "_id": _signal_id("call", sender, c.get("ts"), ""),
            "kind": "missed_call",
            "sender": sender,
            "body": "",
            "otp": False,
            "briefed": False,
            "ts": _to_dt(c.get("ts")) or now,
            "source": source,
            "synced_at": now,
        }
        res = db.signals().update_one(
            {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        if res.upserted_id is not None:
            new_calls += 1

    for n in notifications or []:
        app = str(n.get("app") or "").strip()       # 출처 앱(라벨 또는 패키지)
        title = str(n.get("title") or "").strip()
        text = str(n.get("text") or "").strip()
        if not (title or text):
            continue
        otp = _is_otp(text)
        # 푸시는 수집 시각(ts)이 매번 달라(앱이 DateTime.now로 찍음) 같은 알림이
        # 중복 저장되던 문제 → id의 ts를 '날짜' 단위로. 같은 앱·제목·본문이면
        # 같은 날 1건만 (upsert가 이후 재수신을 스킵). 다음 날 같은 알림은 새 건.
        ts_dt = _to_dt(n.get("ts")) or now
        doc = {
            "_id": _signal_id("notif", f"{app}|{title}", ts_dt.strftime("%Y%m%d"), text),
            "kind": "notification",
            "app": app,
            "sender": title or app,
            "body": text,
            "otp": otp,
            "briefed": otp,
            "ts": _to_dt(n.get("ts")) or now,
            "source": source,
            "synced_at": now,
        }
        res = db.signals().update_one(
            {"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        if res.upserted_id is not None:
            new_notif += 1

    # 부재중 전화는 '회신 필요' 액션이라 신선도가 중요 — 48h 지난 미요약 부재중은
    # 띄우지 말고 조용히 age-out(briefed 마킹). 수집기 lastSync 리셋으로 과거 통화기록이
    # 통째로 재수집돼도 11일 전 통화가 '오늘 회신 필요'로 둔갑하지 않게 한다.
    stale = list(db.signals().find({
        "kind": "missed_call", "briefed": {"$ne": True},
        "ts": {"$lt": now - _CALL_FRESH},
    }, {"_id": 1}))
    if stale:
        db.signals().update_many(
            {"_id": {"$in": [s["_id"] for s in stale]}},
            {"$set": {"briefed": True, "aged_out": True}})

    # 요약 대상 = 아직 brief에 안 들어간 비-OTP 신호 (최근 7일 — 그 전 것은 age-out,
    # 단 어드민 rebrief로 윈도우 무시하고 강제 요약 가능).
    pending = list(
        db.signals().find({
            "briefed": {"$ne": True},
            "otp": {"$ne": True},
            "ts": {"$gte": now - timedelta(days=7)},
        }).sort("ts", 1).limit(50))

    # 동시 호출 가드(백그라운드↔포그라운드 희귀 겹침) — 직전 brief가 25초 이내면
    # 이번엔 요약 보류(pending 보존 → 다음 주기 자연 재시도). 30분 정상 주기엔 무영향.
    last_brief = db.signal_briefs().find_one(sort=[("ts", -1)])
    if (pending and last_brief and isinstance(last_brief.get("ts"), datetime)
            and (now - last_brief["ts"]).total_seconds() < 25):
        return {"new_sms": new_sms, "new_calls": new_calls,
                "new_notif": new_notif,
                "sms_count": 0, "call_count": 0, "notif_count": 0, "summary": ""}

    sms_count, call_count, notif_count, summary = _summarize_pending(pending, now)
    try:                                    # 결제 → 가계부 (스마트 액션, 멱등)
        import ledger
        ledger.sync_from_briefs(now.date())
    except Exception as e:
        print(f"[signals] ledger sync 실패: {e}", flush=True)
    return {"new_sms": new_sms, "new_calls": new_calls, "new_notif": new_notif,
            "sms_count": sms_count, "call_count": call_count,
            "notif_count": notif_count, "summary": summary}


# 카테고리 → 알림용 한글 라벨·정렬 우선순위
_CAT_LABEL = {
    "action_needed": "당장 액션", "attention": "관심", "acquaintance": "지인",
    "low": "일반", "spam": "스팸",
}


def _parse_items(raw_json: Any, valid_ids: set) -> List[Dict[str, Any]]:
    """LLM 분류 결과 → 정규화된 item 리스트 (카테고리 검증·id 필터·feedback 초기화)."""
    out: List[Dict[str, Any]] = []
    for it in (raw_json or {}).get("items", []) if isinstance(raw_json, dict) else []:
        cat = it.get("category")
        if cat not in SIGNAL_CATEGORIES:
            cat = "low"
        sids = [s for s in (it.get("signal_ids") or []) if s in valid_ids]
        out.append({
            "category": cat,
            "sender": str(it.get("sender") or "").strip(),
            "summary": str(it.get("summary") or "").strip(),
            "signal_ids": sids,
            "feedback": None,           # 유저가 "부정확" 표시하면 채워짐
        })
    # 우선순위 정렬 (당장 액션 먼저)
    out.sort(key=lambda x: SIGNAL_CATEGORIES.index(x["category"]))
    return out


def _compose_summary(items: List[Dict[str, Any]]) -> str:
    """구조화 items → 푸시 알림용 짧은 텍스트 (당장 액션·관심 위주)."""
    if not items:
        return ""
    lines: List[str] = []
    for it in items:
        if it["category"] in ("action_needed", "attention", "acquaintance"):
            lines.append(f"· [{_CAT_LABEL[it['category']]}] {it['summary']}")
    spam_n = sum(1 for it in items if it["category"] == "spam")
    low_n = sum(1 for it in items if it["category"] == "low")
    tail = []
    if low_n:
        tail.append(f"일반 {low_n}")
    if spam_n:
        tail.append(f"스팸 {spam_n}")
    if tail:
        lines.append("· " + " · ".join(tail))
    return "\n".join(lines[:6])


def _load_excludes() -> List[str]:
    """어드민이 지정한 요약 제외 패턴 — settings.signal_excludes.patterns (한 줄당 하나)."""
    try:
        doc = db.settings().find_one({"_id": "signal_excludes"})
        return [str(p).strip() for p in (doc or {}).get("patterns", []) if str(p).strip()]
    except Exception:
        return []


def _is_excluded(sig: Dict[str, Any], patterns: List[str]) -> bool:
    """발신자·앱·본문 중 하나라도 패턴(부분일치·대소문자 무시)을 포함하면 제외."""
    hay = " ".join([
        str(sig.get("sender") or ""),
        str(sig.get("app") or ""),
        str(sig.get("body") or ""),
    ]).lower()
    return any(p.lower() in hay for p in patterns)


def _dedup_signals(pending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LLM 요약 전 코드 중복 제거 — 같은 (종류·발신자·본문)이면 대표 1건만.

    앱이 같은 알림을 6ms~수초 차이로 거듭 올리거나(중복 수신) 같은 문자가 여러 번
    잡히는 경우를, 시각 차이와 무관하게 한 신호로 본다. 발신자·본문이 정확히 같으면 중복.
    (LLM 분류에 같은 걸 두 번 넘기지 않음 — 신호 처리를 LLM에만 맡기지 않는 첫 관문.)
    """
    seen: Dict[tuple, Dict[str, Any]] = {}
    for p in pending:
        key = (p.get("kind"), (p.get("sender") or "").strip(),
               (p.get("body") or "").strip())
        seen.setdefault(key, p)
    return list(seen.values())


def _summarize_pending(pending: List[Dict[str, Any]], now: datetime) -> tuple:
    """pending 신호 → 로컬 LLM 분류·요약 + brief(items) 저장 + briefed 마킹.

    요약 성공 시에만 마킹(실패 시 다음 기회 재시도). alias 미설정이면 저장만
    — SMS 본문을 클라우드로 폴백하지 않는다(프라이버시 원칙).
    반환: (sms_count, call_count, notif_count, summary).
    """
    # 어드민 지정 제외 패턴 — 매칭 신호는 요약에서 빼고 briefed 마킹(원본은 raw에 남음).
    patterns = _load_excludes()
    if patterns and pending:
        ex_ids = {p["_id"] for p in pending if _is_excluded(p, patterns)}
        if ex_ids:
            db.signals().update_many(
                {"_id": {"$in": list(ex_ids)}},
                {"$set": {"briefed": True, "excluded": True}})
            pending = [p for p in pending if p["_id"] not in ex_ids]

    # 코드 중복 제거 — 같은 발신자·본문은 LLM에 한 번만 넘긴다.
    pending = _dedup_signals(pending)

    sms_count = sum(1 for p in pending if p["kind"] == "sms")
    call_count = sum(1 for p in pending if p["kind"] == "missed_call")  # 부재중만
    notif_count = sum(1 for p in pending if p["kind"] == "notification")
    summary = ""
    items: List[Dict[str, Any]] = []
    if pending:
        alias = task_alias("signals") or ""
        if alias:
            try:
                r = llm.call(alias, _brief_prompt(pending, now), system=SIGNALS_SYSTEM,
                             expect_json=True)
                items = _parse_items(
                    r.get("json") or _loads(r.get("text")), {p["_id"] for p in pending})
                summary = _compose_summary(items)
            except Exception as e:
                summary = f"(요약 실패: {e})"
        if items and not summary.startswith("(요약 실패"):
            ids = sorted(p["_id"] for p in pending)
            # 같은 신호 조합 → 같은 brief_id(멱등). 동시 sync race로 두 번 요약돼도
            # upsert라 brief는 1건만 남는다(데스크 당장 처리 중복의 근본 차단).
            brief_id = "brief-" + hashlib.sha1("|".join(ids).encode()).hexdigest()[:16]
            db.signal_briefs().update_one(
                {"_id": brief_id},
                {"$setOnInsert": {
                    "_id": brief_id,
                    "ts": now,
                    "summary": summary,        # 알림용 짧은 텍스트 (items에서 합성)
                    "items": items,            # 구조화 분류 결과
                    "sms_count": sms_count,
                    "call_count": call_count,
                    "notif_count": notif_count,
                    "source_ids": ids,
                }},
                upsert=True)
            db.signals().update_many(
                {"_id": {"$in": ids}},
                {"$set": {"briefed": True}})
    return sms_count, call_count, notif_count, summary


def _loads(text: Optional[str]) -> Any:
    """LLM 텍스트에서 첫 JSON 객체 관대 파싱 (expect_json 미지원 백엔드 폴백)."""
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def rebrief_pending(limit: int = 100) -> Dict[str, Any]:
    """미요약 비-OTP 신호 전체를 윈도우 무시하고 강제 요약 (어드민 액션).

    48h/7일 age-out으로 묻힌 과거 미읽음을 한 번에 요약할 때.
    """
    now = datetime.now()
    pending = list(
        db.signals().find({"briefed": {"$ne": True}, "otp": {"$ne": True}})
        .sort("ts", 1).limit(limit))
    if not pending:
        return {"briefed": 0, "summary": "", "sms_count": 0, "call_count": 0}
    sms_count, call_count, notif_count, summary = _summarize_pending(pending, now)
    ok = bool(summary) and not summary.startswith("(요약 실패")
    return {"briefed": len(pending) if ok else 0, "summary": summary,
            "sms_count": sms_count, "call_count": call_count,
            "notif_count": notif_count}


# ── 조회 (A: 신호 로그 화면 / C: 자정 일기 재료) ──────────────

def _brief_view(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": b["_id"],
        "ts": b["ts"].isoformat() if isinstance(b.get("ts"), datetime) else None,
        "summary": b.get("summary") or "",
        "items": b.get("items") or [],          # 구조화 분류 (구 brief는 빈 리스트)
        "sms_count": b.get("sms_count", 0),
        "call_count": b.get("call_count", 0),
        "notif_count": b.get("notif_count", 0),
    }


def set_item_feedback(brief_id: str, item_index: int,
                      feedback: Optional[str]) -> bool:
    """brief의 한 분류 항목에 피드백 ("inaccurate" 또는 None=해제).

    추후 분석에서 그 발신인 분류를 재고하는 힌트로 쓰인다([_feedback_hints]).
    """
    b = db.signal_briefs().find_one({"_id": brief_id}, {"items": 1})
    if not b or not (0 <= item_index < len(b.get("items", []))):
        return False
    res = db.signal_briefs().update_one(
        {"_id": brief_id},
        {"$set": {f"items.{item_index}.feedback": feedback}})
    return res.matched_count > 0


def recategorize(signal_ids: List[str], category: str) -> int:
    """디지털 그룹/액션 재분류 — 그 신호들을 포함한 brief 항목들의 category를 바꾼다.

    action_needed로 바꾸면 데스크 '당장 처리'로, 그 외(관심/지인/일반/스팸)면 '대신 읽어드림'으로
    즉시 이동(둘 다 brief 항목 category를 라이브로 읽으므로). 반환=수정된 brief 수.
    """
    if category not in SIGNAL_CATEGORIES:
        return 0
    sids = {s for s in (signal_ids or []) if s}
    if not sids:
        return 0
    n = 0
    for b in db.signal_briefs().find({"items.signal_ids": {"$in": list(sids)}}):
        items = b.get("items") or []
        changed = False
        for it in items:
            if any(s in sids for s in (it.get("signal_ids") or [])):
                if it.get("category") != category:
                    it["category"] = category
                    changed = True
        if changed:
            db.signal_briefs().update_one({"_id": b["_id"]}, {"$set": {"items": items}})
            n += 1
    return n


def _signal_view(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s["_id"],
        "kind": s.get("kind"),
        "sender": s.get("sender") or "",
        "body": s.get("body") or "",
        "otp": bool(s.get("otp")),
        "excluded": bool(s.get("excluded")),   # 어드민 제외 규칙에 걸린 신호
        "ts": s["ts"].isoformat() if isinstance(s.get("ts"), datetime) else None,
    }


def recent(brief_limit: int = 40, signal_limit: int = 80) -> Dict[str, Any]:
    """신호 로그 화면용 — 과거 brief 타임라인 + 원본 신호 목록(최신순)."""
    briefs = [
        _brief_view(b)
        for b in db.signal_briefs().find().sort("ts", -1).limit(brief_limit)
    ]
    raw = [
        _signal_view(s)
        for s in db.signals().find().sort("ts", -1).limit(signal_limit)
    ]
    return {"briefs": briefs, "signals": raw}


# 카테고리 우선순위 (낮을수록 위·긴급)
_CAT_ORDER = {"action_needed": 0, "attention": 1, "acquaintance": 2,
              "low": 3, "spam": 4}


def today_digest(target: Optional[date] = None) -> Dict[str, Any]:
    """오늘 받은 신호를 발신자별로 묶어 요약 — 실시간 누적, 안 날린다.

    대신 읽어드림의 본체. 중구난방 알림을 한 곳에 모아: 발신자별 그룹 + 건수 +
    요약 줄(중복 제거) + 대표 카테고리. low/spam도 버리지 않고 묶어서 보여준다.
    30분 brief가 누적될 때마다 '지금까지' 최신 상태를 반영(다음날이 아니라).
    """
    target = target or date.today()
    t0 = datetime.combine(target, dtime.min)
    t1 = datetime.combine(target, dtime.max)
    groups: Dict[str, Dict[str, Any]] = {}
    seen_sids: set = set()
    cat_count: "collections.Counter" = collections.Counter()
    # 원본 신호 맵(그날치) — 출처 앱(패키지)·본문 URL 보강용(앱 열기·링크 열기).
    sig_map = {s["_id"]: s for s in db.signals().find({"ts": {"$gte": t0, "$lte": t1}})}
    for b in db.signal_briefs().find({"ts": {"$gte": t0, "$lte": t1}}).sort("ts", 1):
        ts = b.get("ts")
        ts_iso = ts.isoformat() if isinstance(ts, datetime) else None
        for it in b.get("items", []):
            cat = it.get("category", "low")
            if cat == "action_needed":
                continue                       # 당장 처리(별도 섹션)에서 다룸
            sids = [s for s in (it.get("signal_ids") or []) if s]
            if any(s in seen_sids for s in sids):
                continue                       # 같은 신호 중복 요약 제외
            seen_sids.update(sids)
            sender = (it.get("sender") or "(알 수 없음)").strip()
            cat_count[cat] += 1
            summary = (it.get("summary") or "").strip()
            g = groups.get(sender)
            if not g:
                g = {"sender": sender, "category": cat, "lines": [],
                     "count": 0, "last_ts": ts_iso,
                     "sids": [], "app": "", "urls": []}
                groups[sender] = g
            if summary and summary not in g["lines"]:
                g["lines"].append(summary)
            g["count"] += 1
            g["last_ts"] = ts_iso or g["last_ts"]
            g["sids"].extend(sids)             # 재분류·열기 대상(이 그룹의 원본 신호)
            for sid in sids:                   # 출처 앱·본문 URL 보강
                sg = sig_map.get(sid)
                if not sg:
                    continue
                if not g["app"] and sg.get("kind") == "notification" and sg.get("app"):
                    g["app"] = sg["app"]
                for u in _extract_urls(sg.get("body") or ""):
                    if u not in g["urls"]:
                        g["urls"].append(u)
            if _CAT_ORDER.get(cat, 3) < _CAT_ORDER.get(g["category"], 3):
                g["category"] = cat            # 발신자 대표 = 가장 긴급한 것
    out = sorted(groups.values(),
                 key=lambda g: (_CAT_ORDER.get(g["category"], 3), -g["count"]))
    return {
        "date": target.isoformat(),
        "groups": out,
        "totals": {k: cat_count.get(k, 0) for k in _CAT_ORDER},
        "sender_count": len(groups),
        "signal_count": len(seen_sids),
    }


def signals_for_day(target: date) -> List[Dict[str, Any]]:
    """그날 받은 비-OTP 신호 — 자정 일기 재료 (발신인·본문·부재중, 시간순)."""
    t0 = datetime.combine(target, dtime.min)
    t1 = datetime.combine(target, dtime.max)
    out: List[Dict[str, Any]] = []
    for s in db.signals().find(
        {"ts": {"$gte": t0, "$lte": t1}, "otp": {"$ne": True}}
    ).sort("ts", 1):
        out.append({
            "종류": "문자" if s.get("kind") == "sms" else "부재중 전화",
            "보낸이": s.get("sender") or "(알 수 없음)",
            "시각": s["ts"].strftime("%H:%M") if isinstance(s.get("ts"), datetime) else "",
            "내용": s.get("body") or "",
        })
    return out
