"""서술 저널 — 일/주/월 (semantic 계층).

요약-of-요약 압축이 아니라 **서술 일기 + 회고**. 일 저널은 검색 1차 소스(임베딩),
주/월은 그 위 회고 계층. 정본 평문(corpus/)은 불변, journals는 검색 가능한 추상.
"""

import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

import db
import embedding as embedding_mod
from agent import llm, personas
from config import VAULT_DIR
from nightly_common import records_brief, resolve_alias

# 일기·회고는 긴 서술 — opus가 thinking+긴 출력으로 전역 NEST_TIMEOUT(300s)을
# 넘겨 타임아웃나던 것. 이 생성 호출들만 넉넉히(자정 배치라 길어도 무방).
_DIGEST_TIMEOUT = 900


# ── 프롬프트 ────────────────────────────────────────────────

DAILY_JOURNAL_SYSTEM = f"""당신은 유저의 하루를 '일기'로 적습니다. 요약·압축이 아니라, 그날 있었던 일을 시간 순서대로 서술합니다.

**메타 발언 절대 금지**: "형식이 정해져 있지 않으니", "여기 작성해드릴게요", "필요하면 다른 형식으로" 같은 자기 진행상황·옵션 안내 일절 X. 첫 줄부터 본문 시작.

원칙:
- **화자 구분 — 누가 한 말인지 절대 헷갈리지 말 것.** 재료엔 아빠가 아닌 사람·동반자의 말이 섞여 있다.
  · 기록의 `user_comment`만 아빠가 직접 쓴 말이다. `insight`·`suggestion`·`vlm`은 **네(베르)가 그 사진/메모에 단 코멘트**지 아빠 말이 아니다.
  · {personas.SENDER_ATTRIBUTION} 아빠가 '흐름'에서 직접 한 말이 아니면, 다 아빠에게 온 말이거나 아빠 곁에서 남들끼리 오간 말이다.
- {personas.WHO_PAID}
- **요약하지 말 것.** 그날의 구체적 디테일(무엇을·언제·어떤 맥락이었는지)을 살려 시간 순서로 서술한다. 사소하거나 드물어 보이는 디테일도 버리지 않는다 — 나중에 검색·회상의 단서가 된다.
- 1인칭 관찰자 시점의 자연스러운 한국어 산문. 아침·낮·저녁의 흐름이 드러나게. 정형 헤더·불릿 나열보다 흐르는 문장.
- 기록이 적은 날은 짧게, 많은 날은 길게. 억지로 늘이거나 줄이지 않는다.
- **유저는 하루를 전부 기록하지 않는다 — 매우 산발적이다.** 기록과 기록 사이 빈 시간에도 분명 무언가를 하고 있었으니, 적힌 조각만으로 하루 전체를 단정하거나 빈 시간을 '아무것도 안 한 날·쉰 날'로 서술하지 말 것. 보이지 않는 대부분이 있다는 전제로, 적힌 조각만 충실히 적는다.
- 본문 끝에 (해당될 때만, 없으면 생략):
  - ⚠️ 며칠째 무언급된 thread를 부드럽게 짚어줌 ("MX Master 4 thread 5일째 무언급 — 마무리됐나요?")
  - 👍 useful/interesting 표시한 항목들의 공통점 한 줄

상위 헤더(# 날짜)는 호출자가 붙임. 정본 평문은 corpus/에 그대로 있고, 이건 그 위의 검색 가능한 서술 저널(semantic 계층)."""


WEEKLY_JOURNAL_SYSTEM = """당신은 유저의 한 주를 돌아보는 '주간 회고'를 씁니다. 재료는 그 주의 일별 일기들입니다.

**메타 발언 절대 금지**: 진행상황·옵션 안내 X. 첫 줄부터 본문.

원칙:
- 압축 요약이 아니라 **회고 서술**: 한 주의 흐름·변화·반복된 주제를 이야기하듯 짚는다. 일기에 있던 구체적 디테일을 살리되, 며칠에 걸친 연결·패턴을 드러낸다.
- 동반자의 시선으로 **피드백**을 곁들인다: 무언가 진척됐거나 막혔거나 반복되는 게 보이면 부드럽게 짚어주고, 다음 주에 도움될 관점·제안을 1~2개.
- 자연스러운 한국어 산문. 억지로 길게 늘이지 않는다.

상위 헤더(# 주)는 호출자가 붙임. 원본 일기·정본 평문은 그대로 있고, 이건 그 위의 회고 계층."""


MONTHLY_JOURNAL_SYSTEM = """당신은 유저의 한 달을 돌아보는 '월간 회고'를 씁니다. 재료는 그 달의 일별 일기(와 있으면 주간 회고)들입니다.

**메타 발언 절대 금지**: 진행상황·옵션 안내 X. 첫 줄부터 본문.

원칙:
- 압축 요약이 아니라 **회고 서술**: 한 달의 큰 흐름·관심사의 이동·꾸준했던 것과 사라진 것을 이야기한다. 구체적 사건·디테일을 근거로 들되 한 달 단위의 의미를 짚는다.
- 동반자의 시선으로 **피드백·회고**: 잘된 점, 반복된 패턴, 챙기면 좋을 것을 따뜻하게. 다음 달 관점·제안 1~2개.
- 자연스러운 한국어 산문.

상위 헤더(# 월)는 호출자가 붙임. 원본 일기·정본 평문은 그대로 있고, 이건 그 위의 회고 계층."""


# ── 일 저널 ─────────────────────────────────────────────────

def aggregate_reactions(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """그 날 record들의 반응 집계 (취향 신호).

    섹션별 reactions(analysis|comment|discovery)는 "섹션:값" 키로,
    legacy 단일 reaction은 값 그대로 — 둘 다 한 dict에 합산.
    """
    counts: Dict[str, int] = {}
    for r in records:
        rxn = r.get("reaction")
        if rxn:
            counts[rxn] = counts.get(rxn, 0) + 1
        for sec, val in (r.get("reactions") or {}).items():
            if val:
                key = f"{sec}:{val}"
                counts[key] = counts.get(key, 0) + 1
    return counts


def make_daily_journal(
    records: List[Dict[str, Any]],
    target: date,
    silent_threads: Optional[List[Dict[str, Any]]] = None,
    reactions: Optional[Dict[str, int]] = None,
    signals: Optional[List[Dict[str, Any]]] = None,
    visits: Optional[List[str]] = None,
) -> str:
    """그날 기록 → 시간순 서술 일기 본문(# 날짜 헤더 포함)."""
    alias = resolve_alias("daily_digest")
    if not alias:
        return f"# {target.isoformat()}\n\n(daily_digest alias 미설정 — Nest에 enabled 모델 없음)\n"
    parts: List[str] = [
        f"## 오늘({target.isoformat()}) 기록 ({len(records)}건, 시간순)",
        json.dumps(records_brief(records), ensure_ascii=False, indent=2),
    ]
    if visits:
        parts.append("\n## 📍 오늘 다닌 곳 (체류 감지 — 동선·머문 시간. 하루 흐름의 뼈대로 자연스럽게 녹이되 나열하듯 늘어놓지 말 것)")
        parts.append("\n".join(f"- {ln}" for ln in visits))
    if signals:
        parts.append(f"\n## 📨 오늘 받은 연락 (문자·카톡·슬랙 등 — {personas.SENDER_ATTRIBUTION_SHORT}. 의미 있는 배경만 자연스럽게 녹이고 광고·스팸은 무시)")
        parts.append(json.dumps(signals, ensure_ascii=False, indent=1))
    try:
        import ledger as ledger_mod
        _pays = [it for it in ledger_mod.today(target).get("items", [])
                 if it.get("kind") != "income"]
    except Exception:
        _pays = []
    if _pays:
        parts.append(f"\n## 💳 이 날 아빠가 결제한 내역 ({personas.WHO_PAID_SHORT})")
        parts.append("\n".join(
            f"- {it.get('merchant') or it.get('memo') or '결제'} {it.get('amount', 0):,}원"
            f"{' (' + it['method'] + ')' if it.get('method') else ''}" for it in _pays))
    if silent_threads:
        parts.append("\n## ⚠️ 펜딩 환기 후보 (며칠째 무언급 — 일기 마지막에 부드럽게 짚어주기)")
        parts.append(json.dumps(silent_threads, ensure_ascii=False, indent=2))
    if reactions and sum(reactions.values()) > 0:
        parts.append("\n## 👍 오늘의 반응 집계 (섹션:값 — analysis=분석 정확도, comment=코멘트, discovery=디스커버리)")
        parts.append(json.dumps(reactions, ensure_ascii=False))
        parts.append("(긍정 반응(comment:like·discovery:interesting 등) 항목들의 공통점을 취향 메모에 살짝. "
                     "comment:dislike·analysis:wrong이 보이면 어떤 게 아빠와 안 맞았는지도 한 줄.)")
    prompt = "\n".join(parts) + "\n\n위 기록으로 오늘의 일기를 시간 순서대로 서술하세요(요약 금지)."
    # 실패(타임아웃·과부하·인증 등)는 호출자로 전파 — 실패 문자열을 본문으로 저장하지 않기
    # 위해. 일시적 오류는 call_retry가 백오프 재시도, 영구 오류(401 등)는 즉시 raise.
    r = llm.call_retry(alias, prompt, system=DAILY_JOURNAL_SYSTEM, timeout=_DIGEST_TIMEOUT)
    body = (r.get("text") or "").strip()
    if not body:
        raise RuntimeError("일기 생성: 빈 응답")
    return f"# {target.isoformat()}\n\n{body}\n"


DAY_SUMMARY3_SYSTEM = """당신은 유저의 하루 일기를 딱 3줄로 요약합니다.
- 그날의 핵심 3가지를 각각 한 줄로, 구체적으로(무엇을 했는지 — 막연한 감상 X).
- 메타·인사 없이 본문만. 각 줄 짧게, '~함/~했음/~다녀옴' 같은 사실 종결.
- 정확히 3줄. 번호·불릿·따옴표 없이 줄바꿈으로만 구분."""


def make_day_summary3(body_text: str) -> str:
    """일기 본문 → 그날 핵심 3줄 (표지 '오늘의 한 줄'용). 미설정/실패면 ''.

    줄바꿈으로 합친 문자열 반환 — 표지가 그대로 여러 줄로 표시한다.
    """
    alias = resolve_alias("daily_digest")
    body = (body_text or "").strip()
    # 생성 실패 마커거나 본문(헤더 제외)이 빈약하면 요약하지 않음 — 빈 하루를
    # 억지로 요약하려다 "요약할 본문이 없습니다" 같은 메타 응답이 나오는 것 방지.
    core = "\n".join(
        ln for ln in body.splitlines() if not ln.lstrip().startswith("#")).strip()
    if not alias or "(일기 생성 실패" in body or len(core) < 20:
        return ""
    try:
        r = llm.call_retry(alias,
                           f"[오늘의 일기]\n{body}\n\n이 하루를 3줄로 요약하세요.",
                           system=DAY_SUMMARY3_SYSTEM, timeout=_DIGEST_TIMEOUT)
        lines = [ln.strip(" -·•\t0123456789.")
                 for ln in (r.get("text") or "").splitlines() if ln.strip()]
        return "\n".join([ln for ln in lines if ln][:3])
    except Exception:
        return ""   # 요약은 부가물 — 실패해도 빈 문자열(일기 본문엔 영향 없음)


def write_daily_digest_file(target: date, text: str) -> str:
    """일 저널을 vault digest/{date}.md 로 (사람용). 반환: 파일 경로."""
    digest_dir = Path(VAULT_DIR).parent / "digest"
    digest_dir.mkdir(parents=True, exist_ok=True)
    p = digest_dir / f"{target.isoformat()}.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def save_day_journal(
    target: date,
    body_text: str,
    record_count: int,
    reactions: Dict[str, int],
    start: datetime,
    end: datetime,
    summary3: str = "",
) -> bool:
    """일 서술 일기를 journals(day)에 upsert + 임베딩 (검색은 day 저널만)."""
    return _upsert_journal(
        f"day-{target.isoformat()}", "day", target.isoformat(),
        start, end, body_text, record_count, reactions, summary3=summary3,
    )


# ── 주/월 회고 ──────────────────────────────────────────────

def run_weekly(target: Optional[date] = None) -> Dict[str, Any]:
    """주간 회고 — target(또는 지난 주)이 속한 월~일 주를 일별 일기로 회고."""
    base = target or (date.today() - timedelta(days=7))
    monday = base - timedelta(days=base.weekday())
    start = datetime.combine(monday, datetime.min.time())
    end = start + timedelta(days=7)
    iso = monday.isocalendar()
    label = f"{iso[0]}-W{iso[1]:02d}"
    jid = f"week-{label}"

    day_journals = gather_day_journals(start, end)
    if not day_journals:
        return {"ok": True, "id": jid, "skipped": "no day journals that week"}

    reactions = _sum_reactions(day_journals)
    record_count = sum(int(j.get("record_count") or 0) for j in day_journals)
    import ledger as ledger_mod
    settle = ledger_mod.settlement_material("week", monday)
    body = _make_period_journal(
        WEEKLY_JOURNAL_SYSTEM, f"# {label} 주간 회고",
        f"{label} ({monday.isoformat()}~{(end - timedelta(days=1)).date().isoformat()})",
        day_journals, reactions, "weekly_journal", settle,
    )
    _write_period_vault(jid, body)
    embedded = _upsert_journal(jid, "week", label, start, end, body, record_count, reactions)
    return {"ok": True, "id": jid, "days": len(day_journals),
            "embedded": embedded, "preview": body[:200]}


def run_monthly(target: Optional[date] = None) -> Dict[str, Any]:
    """월간 회고 — target(또는 지난 달)의 일별 일기 + 주간 회고를 재료로."""
    base = target or (date.today().replace(day=1) - timedelta(days=1))
    month_first = base.replace(day=1)
    if month_first.month == 12:
        next_month = month_first.replace(year=month_first.year + 1, month=1)
    else:
        next_month = month_first.replace(month=month_first.month + 1)
    start = datetime.combine(month_first, datetime.min.time())
    end = datetime.combine(next_month, datetime.min.time())
    label = month_first.strftime("%Y-%m")
    jid = f"month-{label}"

    day_journals = gather_day_journals(start, end)
    week_journals = _gather_journals("week", start, end)
    if not day_journals and not week_journals:
        return {"ok": True, "id": jid, "skipped": "no journals that month"}

    reactions = _sum_reactions(day_journals)
    record_count = sum(int(j.get("record_count") or 0) for j in day_journals)
    import ledger as ledger_mod
    settle = ledger_mod.settlement_material("month", month_first)
    body = _make_period_journal(
        MONTHLY_JOURNAL_SYSTEM, f"# {label} 월간 회고", label,
        day_journals + week_journals, reactions, "monthly_journal", settle,
    )
    _write_period_vault(jid, body)
    embedded = _upsert_journal(jid, "month", label, start, end, body, record_count, reactions)
    return {"ok": True, "id": jid, "days": len(day_journals),
            "weeks": len(week_journals), "embedded": embedded, "preview": body[:200]}


def gather_day_journals(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return _gather_journals("day", start, end)


def _gather_journals(kind: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """기간 [start,end) 안의 kind 저널을 시간순으로."""
    return list(
        db.journals()
        .find({"kind": kind, "period_start": {"$gte": start, "$lt": end}})
        .sort("period_start", 1)
    )


def _sum_reactions(journals: List[Dict[str, Any]]) -> Dict[str, int]:
    total = {"interesting": 0, "useful": 0, "skip": 0}
    for j in journals:
        rs = j.get("reaction_signal") or {}
        for k in total:
            total[k] += int(rs.get(k) or 0)
    return total


def _make_period_journal(
    system: str,
    header: str,
    label: str,
    journals: List[Dict[str, Any]],
    reactions: Dict[str, int],
    alias_key: str,
    settlement: str = "",
) -> str:
    """일/주 저널 재료 → 주/월 회고 본문(header 포함). settlement=가계부 결산(있으면 녹임)."""
    alias = resolve_alias(alias_key) or resolve_alias("daily_digest")
    if not alias:
        return f"{header}\n\n(회고 alias 미설정 — Nest에 enabled 모델 없음)\n"
    parts: List[str] = [f"## 재료 — {label} 저널 ({len(journals)}건, 시간순)"]
    for j in journals:
        t = (j.get("text") or "").strip()
        if t:
            parts.append(t)
    if reactions and sum(reactions.values()) > 0:
        parts.append(f"\n## 👍 이 기간 이모지 반응 집계\n{json.dumps(reactions, ensure_ascii=False)}")
    if settlement:
        parts.append("\n## 💰 이 기간 가계부 결산 (회고 끝에 소비 흐름을 자연스럽게 한두 줄로 "
                     "짚어줘 — 숫자 나열 말고 눈에 띄는 것 한둘. 예: '이번 달은 외식이 늘었네요')\n"
                     + settlement)
    prompt = "\n\n".join(parts) + "\n\n위 저널들로 회고를 서술하세요(압축 요약 금지, 회고+피드백)."
    # 실패는 전파 — run_weekly/monthly가 저장 전에 호출하므로 예외 시 저장 스킵(빈 슬롯).
    r = llm.call_retry(alias, prompt, system=system, timeout=_DIGEST_TIMEOUT)
    body = (r.get("text") or "").strip()
    if not body:
        raise RuntimeError("회고 생성: 빈 응답")
    return f"{header}\n\n{body}\n"


def _write_period_vault(jid: str, text: str) -> None:
    """주/월 회고를 vault journal/ 디렉토리에 사람용 마크다운으로."""
    jdir = Path(VAULT_DIR).parent / "journal"
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / f"{jid}.md").write_text(text, encoding="utf-8")


def _upsert_journal(
    jid: str,
    kind: str,
    date_label: str,
    start: datetime,
    end: datetime,
    text: str,
    record_count: int,
    reactions: Dict[str, int],
    summary3: str = "",
) -> bool:
    """서술 저널(일/주/월)을 journals 컬렉션에 upsert + 임베딩.

    재실행 시 idempotent(같은 _id upsert). 임베딩은 graceful — 실패해도 본문은 남음.
    반환: 임베딩 부착 성공 여부.
    """
    now = datetime.now()
    db.journals().update_one(
        {"_id": jid},
        {
            "$set": {
                "kind": kind,
                "date": date_label,
                "period_start": start,
                "period_end": end,
                "text": text,
                "summary3": summary3,
                "record_count": record_count,
                "reaction_signal": reactions,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    try:
        return embedding_mod.embed_journal(jid, text)
    except Exception:
        return False


# ── 조회 ────────────────────────────────────────────────────

def list_journals(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """journals 목록(최신순). kind 지정 시 필터. 본문 제외 메타만."""
    q = {"kind": kind} if kind else {}
    out: List[Dict[str, Any]] = []
    for j in db.journals().find(q, {"text": 0, "embedding": 0}).sort("period_start", -1):
        for f in ("period_start", "period_end", "created_at", "updated_at"):
            v = j.get(f)
            if hasattr(v, "isoformat"):
                j[f] = v.isoformat()
        out.append(j)
    return out


def read_journal(jid: str) -> Optional[Dict[str, Any]]:
    """journals 단건 본문(임베딩 제외)."""
    j = db.journals().find_one({"_id": jid}, {"embedding": 0})
    if not j:
        return None
    for f in ("period_start", "period_end", "created_at", "updated_at"):
        v = j.get(f)
        if hasattr(v, "isoformat"):
            j[f] = v.isoformat()
    return j


def list_digests() -> List[Dict[str, Any]]:
    """vault digest/ 안 일 저널 파일 목록 (최신순)."""
    digest_dir = Path(VAULT_DIR).parent / "digest"
    if not digest_dir.exists():
        return []
    files = sorted(digest_dir.glob("*.md"), reverse=True)
    return [{"date": f.stem, "size": f.stat().st_size} for f in files]


def read_digest(date_str: str) -> Optional[str]:
    digest_dir = Path(VAULT_DIR).parent / "digest"
    p = digest_dir / f"{date_str}.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")
