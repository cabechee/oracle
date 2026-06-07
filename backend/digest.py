"""자정 배치 — Layer 3.

하루 끝나면 (수동 또는 launchd cron):
1. thread_judge LLM → 각 record에 thread_ids 부착 (정체성 닻)
2. type_classify LLM → record에 type_hint + tags 부착
3. daily_digest LLM → vault digest/YYYY-MM-DD.md (닫힌 블록)

원칙: 정본 평문(corpus/)은 불변. 다이제스트는 그 위의 닫힌 산출물 — 원본 안 바뀌면
같은 다이제스트가 (대략) 재생성됨. MongoDB record.thread_ids/type/tags는 인덱스 캐시.

수동 트리거: POST /digest/run?target_date=YYYY-MM-DD (안 주면 어제)
"""

import json
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

import nest_client
import db
import threads as threads_mod
import embedding as embedding_mod
from config import VAULT_DIR, TASK_ALIAS


# ── 프롬프트 ────────────────────────────────────────────────

THREAD_JUDGE_SYSTEM = """순수 JSON 분류 작업. 파일·코드·도구 접근 금지 — 오직 user 메시지의 records 텍스트만 보고 판정.

규칙 1: user 메시지의 모든 record가 assignments에 등장.

규칙 2: 같은 주제·물건·인물의 시리즈는 같은 thread.
  ✓ 마우스 사진 3장 (첫 등장 → 잘못 식별 → "이건 MX Master 4야" 정정) → 모두 같은 새 thread "MX Master 4"
  ✓ "여권 어디 있더라" → 며칠 후 "찾았다 서랍에" → 같은 thread "여권 찾기"
  ✓ 옷·SD카드 같은 진짜 일회성 단발 → thread_ids: []
  ✗ 보수적으로 다 빈 배열 두지 말 것. 묶일 가능성 보이면 thread 만들기.

규칙 3: 한 record가 여러 thread에 동시 소속 OK. thread name은 짧은 한국어.

규칙 4: 상태(완료·펜딩) 판단 X — 정체성(연결)만.

출력 = JSON 객체 하나, 그 외 텍스트 절대 없음:
{"assignments":[{"record_id":"rec-...","thread_ids":[17]},{"record_id":"rec-...","thread_ids":[]}],"new_threads":[{"id":17,"name":"MX Master 4","lineage_from":null}]}"""


TYPE_TAG_SYSTEM = """순수 JSON 분류 작업. 파일·코드·도구 접근 금지 — 오직 user 메시지의 records 텍스트만 보고 판정.

규칙 1: user 메시지의 모든 record가 assignments에 등장.

규칙 2: type 필드는 정확히 아래 4개 한국어 단어 중 1개. 그 외 모든 값(영어·새 카테고리·snake_case) 거부됨.
  ✓ "상황" — 현재 일어나는 일·관찰 (식사·풍경·만남·물건 보여주기)
  ✓ "의도" — 하고 싶은 일·계획·고민·결정 대기
  ✓ "맥락" — 정보·자료·메모·링크·영수증·아이디어
  ✓ "산출물" — 만든 것·결과·완료된 일
  ✗ "correction_note" → "상황" 으로 변환
  ✗ "item_photo" → "상황" 으로 변환
  ✗ "user_input" → "맥락" 으로 변환

규칙 3: tags 필드는 한국어 단어 3~5개. 영어·snake_case 거부됨.
  ✓ ["비빔밥", "점심", "야채"]
  ✓ ["마우스", "MX마스터4", "데스크"]
  ✗ ["mouse", "MX_Master_4", "desk_setup"] — 모두 한국어로 변환

출력 = JSON 객체 하나, 그 외 텍스트 절대 없음:
{"assignments":[{"record_id":"rec-...","type":"상황","tags":["비빔밥","점심","야채"]}]}"""


DAILY_JOURNAL_SYSTEM = """당신은 유저의 하루를 '일기'로 적습니다. 요약·압축이 아니라, 그날 있었던 일을 시간 순서대로 서술합니다.

**메타 발언 절대 금지**: "형식이 정해져 있지 않으니", "여기 작성해드릴게요", "필요하면 다른 형식으로" 같은 자기 진행상황·옵션 안내 일절 X. 첫 줄부터 본문 시작.

원칙:
- **요약하지 말 것.** 그날의 구체적 디테일(무엇을·언제·어떤 맥락이었는지)을 살려 시간 순서로 서술한다. 사소하거나 드물어 보이는 디테일도 버리지 않는다 — 나중에 검색·회상의 단서가 된다.
- 1인칭 관찰자 시점의 자연스러운 한국어 산문. 아침·낮·저녁의 흐름이 드러나게. 정형 헤더·불릿 나열보다 흐르는 문장.
- 기록이 적은 날은 짧게, 많은 날은 길게. 억지로 늘이거나 줄이지 않는다.
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


# ── 메인 ────────────────────────────────────────────────────

def run_daily(target_date: Optional[date] = None) -> Dict[str, Any]:
    """target(또는 어제) 자정 배치 실행. 처리 결과 dict 반환."""
    try:
        return _run_daily_inner(target_date)
    except Exception:
        import traceback
        traceback.print_exc()
        raise


def _run_daily_inner(target_date: Optional[date] = None) -> Dict[str, Any]:
    target = target_date or (date.today() - timedelta(days=1))
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    records = list(
        db.records().find({"ts": {"$gte": start, "$lt": end}}).sort("ts", 1)
    )
    if not records:
        return {
            "ok": True,
            "date": target.isoformat(),
            "records": 0,
            "skipped": "no records that day",
        }

    result: Dict[str, Any] = {
        "ok": True,
        "date": target.isoformat(),
        "records": len(records),
    }

    # 1·2) thread + type 동시 호출 (LLM concurrency=2 활용, ~1/2 시간)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_thread = ex.submit(_judge_threads, records)
        f_type = ex.submit(_classify_type_tags, records)
        thread_res = (f_thread.result() or {})
        type_res_concurrent = (f_type.result() or {})
    for a in thread_res.get("assignments", []) or []:
        if not isinstance(a, dict):
            continue
        rid = a.get("record_id")
        tids = a.get("thread_ids") or []
        if rid:
            db.records().update_one(
                {"_id": rid}, {"$set": {"thread_ids": tids}}
            )
    for nt in thread_res.get("new_threads", []) or []:
        if not isinstance(nt, dict):
            continue
        tid = nt.get("id")
        if tid is not None:
            threads_mod.upsert_thread(
                int(tid),
                nt.get("name", f"thread-{tid}"),
                nt.get("lineage_from"),
            )
    result["thread_assignments"] = len(thread_res.get("assignments", []) or [])
    result["new_threads"] = len(thread_res.get("new_threads", []) or [])

    # 2) type + tags 적용 (위 ThreadPoolExecutor에서 동시 fetch한 결과)
    type_res = type_res_concurrent
    for a in type_res.get("assignments", []) or []:
        if not isinstance(a, dict):
            continue
        rid = a.get("record_id")
        if rid:
            db.records().update_one(
                {"_id": rid},
                {"$set": {
                    "type_hint": a.get("type"),
                    "tags": a.get("tags", []) or [],
                }},
            )
    result["type_assignments"] = len(type_res.get("assignments", []) or [])

    # 3) reaction 집계 (코드, LLM X)
    reactions = _aggregate_reactions(records)
    result["reactions"] = reactions

    # 4) silent threads (펜딩 환기 후보) — 3~30일 무언급
    silent = threads_mod.silent_threads(min_days=3, max_days=30)
    result["silent_thread_count"] = len(silent)

    # 5) daily digest (LLM, silent + reactions 포함된 풍부한 prompt)
    digest_text = _make_digest(records, target, silent, reactions)
    digest_dir = Path(VAULT_DIR).parent / "digest"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_path = digest_dir / f"{target.isoformat()}.md"
    digest_path.write_text(digest_text, encoding="utf-8")
    result["digest_path"] = str(digest_path)
    result["digest_preview"] = digest_text[:200]

    # 5b) journals(day) 저장 + 임베딩 — 검색 가능한 semantic 계층
    embedded = _save_day_journal(target, digest_text, len(records), reactions, start, end)
    result["journal_embedded"] = embedded

    # 6) 상위 인덱스 갱신 (코드 aggregate, vault master.md + MongoDB index_meta)
    idx = _update_master_index(target)
    result["index"] = idx

    return result


# ── 주/월 회고 + cron 오케스트레이션 ─────────────────────────

def run_nightly() -> Dict[str, Any]:
    """자정 plist가 호출(target 없음). 어제 일 저널 + (월요일이면)주간 + (1일이면)월간.

    한 cron으로 일/주/월을 모두 처리 — 추가 launchd 불필요. 각 단계 독립 try.
    """
    out: Dict[str, Any] = {}
    out["daily"] = run_daily(None)
    today = date.today()
    if today.weekday() == 0:   # 월요일 = 지난 주(월~일) 완료
        try:
            out["weekly"] = run_weekly()
        except Exception as e:
            out["weekly"] = {"ok": False, "error": str(e)}
    if today.day == 1:         # 매월 1일 = 지난 달 완료
        try:
            out["monthly"] = run_monthly()
        except Exception as e:
            out["monthly"] = {"ok": False, "error": str(e)}
    return out


def run_weekly(target: Optional[date] = None) -> Dict[str, Any]:
    """주간 회고 — target(또는 지난 주)이 속한 월~일 주를 일별 일기로 회고."""
    base = target or (date.today() - timedelta(days=7))
    monday = base - timedelta(days=base.weekday())
    start = datetime.combine(monday, datetime.min.time())
    end = start + timedelta(days=7)
    iso = monday.isocalendar()
    label = f"{iso[0]}-W{iso[1]:02d}"
    jid = f"week-{label}"

    day_journals = _gather_day_journals(start, end)
    if not day_journals:
        return {"ok": True, "id": jid, "skipped": "no day journals that week"}

    reactions = _sum_reactions(day_journals)
    record_count = sum(int(j.get("record_count") or 0) for j in day_journals)
    body = _make_period_journal(
        WEEKLY_JOURNAL_SYSTEM, f"# {label} 주간 회고",
        f"{label} ({monday.isoformat()}~{(end - timedelta(days=1)).date().isoformat()})",
        day_journals, reactions, "weekly_journal",
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

    day_journals = _gather_day_journals(start, end)
    week_journals = _gather_journals("week", start, end)
    if not day_journals and not week_journals:
        return {"ok": True, "id": jid, "skipped": "no journals that month"}

    reactions = _sum_reactions(day_journals)
    record_count = sum(int(j.get("record_count") or 0) for j in day_journals)
    body = _make_period_journal(
        MONTHLY_JOURNAL_SYSTEM, f"# {label} 월간 회고", label,
        day_journals + week_journals, reactions, "monthly_journal",
    )
    _write_period_vault(jid, body)
    embedded = _upsert_journal(jid, "month", label, start, end, body, record_count, reactions)
    return {"ok": True, "id": jid, "days": len(day_journals),
            "weeks": len(week_journals), "embedded": embedded, "preview": body[:200]}


def _gather_day_journals(start: datetime, end: datetime) -> List[Dict[str, Any]]:
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
) -> str:
    """일/주 저널 재료 → 주/월 회고 본문(header 포함)."""
    alias = _resolve_alias(alias_key) or _resolve_alias("daily_digest")
    if not alias:
        return f"{header}\n\n(회고 alias 미설정 — Nest에 enabled 모델 없음)\n"
    parts: List[str] = [f"## 재료 — {label} 저널 ({len(journals)}건, 시간순)"]
    for j in journals:
        t = (j.get("text") or "").strip()
        if t:
            parts.append(t)
    if reactions and sum(reactions.values()) > 0:
        parts.append(f"\n## 👍 이 기간 이모지 반응 집계\n{json.dumps(reactions, ensure_ascii=False)}")
    prompt = "\n\n".join(parts) + "\n\n위 저널들로 회고를 서술하세요(압축 요약 금지, 회고+피드백)."
    try:
        r = nest_client.call(alias=alias, prompt=prompt, system=system)
        body = (r.get("text") or "").strip()
        return f"{header}\n\n{body}\n"
    except Exception as e:
        return f"{header}\n\n(회고 생성 실패: {e})\n"


def _write_period_vault(jid: str, text: str) -> None:
    """주/월 회고를 vault journal/ 디렉토리에 사람용 마크다운으로."""
    jdir = Path(VAULT_DIR).parent / "journal"
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / f"{jid}.md").write_text(text, encoding="utf-8")


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


# ── 내부 helpers ─────────────────────────────────────────────

def _records_brief(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LLM 호출용 — record를 짧게 요약 (각 필드 길이 제한)."""
    brief: List[Dict[str, Any]] = []
    for r in records:
        ts = r.get("ts")
        brief.append({
            "id": r["_id"],
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
            "user_comment": (r.get("user_comment") or "")[:300],
            "vlm": ((r.get("vlm") or {}).get("caption") or "")[:300],
            "insight": ((r.get("insight") or {}).get("text") or "")[:300],
            "suggestion": (r.get("suggestion") or "")[:200],
        })
    return brief


def _resolve_alias(task_key: str) -> Optional[str]:
    """alias 동적 chain: env(TASK_ALIAS) → Nest enabled 첫 모델."""
    env_alias = TASK_ALIAS.get(task_key) or ""
    if env_alias:
        return env_alias
    return nest_client.default_alias()


def _parse_json_safe(text: str) -> Dict[str, Any]:
    """LLM 응답에서 JSON 추출. 코드블록 또는 raw 둘 다 처리."""
    if not text:
        return {}
    # ```json ... ``` 추출
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    # 첫 { ~ 마지막 } 슬라이스
    if "{" in candidate and "}" in candidate:
        candidate = candidate[candidate.index("{"):candidate.rindex("}") + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return {}


def _judge_threads(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    alias = _resolve_alias("thread_judge")
    if not alias:
        return {}
    active = threads_mod.list_active_threads(within_days=60)
    next_id = threads_mod.next_thread_id()
    brief = _records_brief(records)
    prompt = (
        f"## Active threads (최근 60일)\n"
        f"{json.dumps(active, ensure_ascii=False, default=str)}\n\n"
        f"## 오늘 records (총 {len(brief)}건 — 모두 assignments에 등장해야 함)\n"
        f"{json.dumps(brief, ensure_ascii=False)}\n\n"
        f"새 thread는 id={next_id}부터 순차 할당.\n\n"
        f"**위 {len(brief)}개 record_id 전부 assignments에 포함. JSON 객체 하나만, 첫 글자 `{{`.**"
    )
    try:
        r = nest_client.call(
            alias=alias,
            prompt=prompt,
            system=THREAD_JUDGE_SYSTEM,
        )
        raw = r.get("text") or ""
        parsed = _parse_json_safe(raw)
        if not parsed:
            print(
                f"[digest] _judge_threads JSON parse 실패. raw 앞 1500자:\n{raw[:1500]}",
                flush=True,
            )
        else:
            print(
                f"[digest] _judge_threads OK — assignments={len(parsed.get('assignments', []) or [])}, new={len(parsed.get('new_threads', []) or [])}",
                flush=True,
            )
        return parsed
    except Exception as e:
        print(f"[digest] _judge_threads 호출 실패: {e}", flush=True)
        return {}


def _classify_type_tags(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    alias = _resolve_alias("type_classify")
    if not alias:
        return {}
    brief = _records_brief(records)
    prompt = (
        f"## records (총 {len(brief)}건 — 모두 assignments에 등장해야 함)\n"
        f"{json.dumps(brief, ensure_ascii=False)}\n\n"
        f"각 record에 type + tags 부착.\n\n"
        f"**위 {len(brief)}개 record_id 전부 assignments에 포함. JSON 객체 하나만, 첫 글자 `{{`.**"
    )
    try:
        r = nest_client.call(
            alias=alias,
            prompt=prompt,
            system=TYPE_TAG_SYSTEM,
        )
        raw = r.get("text") or ""
        parsed = _parse_json_safe(raw)
        if not parsed:
            print(
                f"[digest] _classify_type_tags JSON parse 실패. raw 앞 1500자:\n{raw[:1500]}",
                flush=True,
            )
        else:
            print(
                f"[digest] _classify_type_tags OK — assignments={len(parsed.get('assignments', []) or [])}",
                flush=True,
            )
        return parsed
    except Exception as e:
        print(f"[digest] _classify_type_tags 호출 실패: {e}", flush=True)
        return {}


def _make_digest(
    records: List[Dict[str, Any]],
    target: date,
    silent_threads: Optional[List[Dict[str, Any]]] = None,
    reactions: Optional[Dict[str, int]] = None,
) -> str:
    alias = _resolve_alias("daily_digest")
    if not alias:
        return f"# {target.isoformat()}\n\n(daily_digest alias 미설정 — Nest에 enabled 모델 없음)\n"
    parts: List[str] = [
        f"## 오늘({target.isoformat()}) 기록 ({len(records)}건, 시간순)",
        json.dumps(_records_brief(records), ensure_ascii=False, indent=2),
    ]
    if silent_threads:
        parts.append(f"\n## ⚠️ 펜딩 환기 후보 (며칠째 무언급 — 일기 마지막에 부드럽게 짚어주기)")
        parts.append(json.dumps(silent_threads, ensure_ascii=False, indent=2))
    if reactions and sum(reactions.values()) > 0:
        parts.append(f"\n## 👍 오늘의 이모지 반응 집계")
        parts.append(json.dumps(reactions, ensure_ascii=False))
        parts.append("(useful/interesting로 표시된 항목들의 공통점을 메모에 살짝)")
    prompt = "\n".join(parts) + "\n\n위 기록으로 오늘의 일기를 시간 순서대로 서술하세요(요약 금지)."
    try:
        r = nest_client.call(alias=alias, prompt=prompt, system=DAILY_JOURNAL_SYSTEM)
        body = (r.get("text") or "").strip()
        return f"# {target.isoformat()}\n\n{body}\n"
    except Exception as e:
        return f"# {target.isoformat()}\n\n(일기 생성 실패: {e})\n"


def _aggregate_reactions(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """그 날 record들의 이모지 반응 집계 (취향 신호)."""
    counts = {"interesting": 0, "useful": 0, "skip": 0}
    for r in records:
        rxn = r.get("reaction")
        if rxn in counts:
            counts[rxn] += 1
    return counts


def _upsert_journal(
    jid: str,
    kind: str,
    date_label: str,
    start: datetime,
    end: datetime,
    text: str,
    record_count: int,
    reactions: Dict[str, int],
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


def _save_day_journal(
    target: date,
    body_text: str,
    record_count: int,
    reactions: Dict[str, int],
    start: datetime,
    end: datetime,
) -> bool:
    """일 서술 일기 저장 (검색은 day 저널만, 주/월은 회고 계층)."""
    return _upsert_journal(
        f"day-{target.isoformat()}", "day", target.isoformat(),
        start, end, body_text, record_count, reactions,
    )


def _update_master_index(target: date) -> Dict[str, Any]:
    """상위 인덱스 갱신 — MongoDB index_meta (월별) + vault index/master.md.
    그날 날짜의 월을 기준으로 그 월 전체 통계를 다시 집계 (idempotent)."""
    month_first = target.replace(day=1)
    if month_first.month == 12:
        next_month = month_first.replace(year=month_first.year + 1, month=1)
    else:
        next_month = month_first.replace(month=month_first.month + 1)
    start = datetime.combine(month_first, datetime.min.time())
    end = datetime.combine(next_month, datetime.min.time())
    month_key = month_first.strftime("%Y-%m")

    # 1) tags top N
    pipe_tags = [
        {"$match": {"ts": {"$gte": start, "$lt": end}, "tags": {"$ne": []}}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 30},
    ]
    top_tags = [
        {"tag": t["_id"], "count": t["count"]}
        for t in db.records().aggregate(pipe_tags)
    ]

    # 2) threads active in this month
    pipe_th = [
        {"$match": {"ts": {"$gte": start, "$lt": end}, "thread_ids": {"$ne": []}}},
        {"$unwind": "$thread_ids"},
        {"$group": {
            "_id": "$thread_ids",
            "count": {"$sum": 1},
            "last_seen": {"$max": "$ts"},
        }},
        {"$sort": {"last_seen": -1}},
    ]
    threads_active: List[Dict[str, Any]] = []
    for t in db.records().aggregate(pipe_th):
        meta = db.threads().find_one({"_id": t["_id"]}) or {}
        ls = t["last_seen"]
        threads_active.append({
            "id": t["_id"],
            "name": meta.get("name", f"thread-{t['_id']}"),
            "count": t["count"],
            "last_seen": ls.isoformat() if hasattr(ls, "isoformat") else ls,
        })

    record_count = db.records().count_documents({"ts": {"$gte": start, "$lt": end}})

    # 3) types 분포
    pipe_type = [
        {"$match": {"ts": {"$gte": start, "$lt": end}, "type_hint": {"$ne": None}}},
        {"$group": {"_id": "$type_hint", "count": {"$sum": 1}}},
    ]
    types_dist = {t["_id"]: t["count"] for t in db.records().aggregate(pipe_type)}

    # MongoDB index_meta upsert
    db.index_meta().update_one(
        {"_id": month_key},
        {"$set": {
            "month": month_key,
            "record_count": record_count,
            "top_tags": top_tags,
            "threads_active": threads_active,
            "types_dist": types_dist,
            "last_updated": datetime.now(),
        }},
        upsert=True,
    )

    # vault index/master.md (사람용 자연어 목차)
    _write_master_md()

    return {
        "month": month_key,
        "record_count": record_count,
        "tags": len(top_tags),
        "threads": len(threads_active),
    }


def _write_master_md() -> None:
    """index_meta의 모든 월 entry → vault index/master.md (사람용 검색 진입점)."""
    months = list(db.index_meta().find().sort("_id", -1))
    lines: List[str] = [
        "# 상위 인덱스 — 검색 진입점",
        "",
        "자정 배치가 매일 갱신. 월별 record 통계 + 자주 등장한 태그 + 활성 thread.",
        "",
    ]
    for m in months:
        lines.append(f"## {m.get('month', '?')}")
        lines.append(f"- 기록 **{m.get('record_count', 0)}**건")
        types_dist = m.get("types_dist") or {}
        if types_dist:
            ts = " · ".join(f"{k} {v}" for k, v in sorted(types_dist.items(), key=lambda x: -x[1]))
            lines.append(f"- 분포: {ts}")
        tags = m.get("top_tags", [])
        if tags:
            tag_str = " · ".join(f"{t['tag']}({t['count']})" for t in tags[:12])
            lines.append(f"- 자주 등장: {tag_str}")
        threads = m.get("threads_active", [])
        if threads:
            t_str = " · ".join(f"#{t['id']} {t['name']}({t['count']})" for t in threads[:12])
            lines.append(f"- 활성 thread: {t_str}")
        lines.append("")
    index_dir = Path(VAULT_DIR).parent / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "master.md").write_text("\n".join(lines), encoding="utf-8")


def read_master_index() -> Optional[str]:
    """vault index/master.md 본문 (사람용 검색 진입점)."""
    p = Path(VAULT_DIR).parent / "index" / "master.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def list_index_meta() -> List[Dict[str, Any]]:
    """MongoDB index_meta 전체 (월별, 최신순)."""
    out: List[Dict[str, Any]] = []
    for m in db.index_meta().find().sort("_id", -1):
        last = m.get("last_updated")
        if hasattr(last, "isoformat"):
            m["last_updated"] = last.isoformat()
        out.append(m)
    return out


# ── 조회 ────────────────────────────────────────────────────

def list_digests() -> List[Dict[str, Any]]:
    """vault digest/ 안 다이제스트 파일 목록 (최신순)."""
    digest_dir = Path(VAULT_DIR).parent / "digest"
    if not digest_dir.exists():
        return []
    files = sorted(digest_dir.glob("*.md"), reverse=True)
    out: List[Dict[str, Any]] = []
    for f in files:
        out.append({
            "date": f.stem,
            "size": f.stat().st_size,
        })
    return out


def read_digest(date_str: str) -> Optional[str]:
    digest_dir = Path(VAULT_DIR).parent / "digest"
    p = digest_dir / f"{date_str}.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")
