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


DAILY_DIGEST_SYSTEM = """당신은 오늘 하루 기록을 닫는 다이제스트를 씁니다.

**메타 발언 절대 금지**: "다이제스트 형식이 정해져 있지 않으니", "여기 작성해드릴게요", "필요하면 다른 형식으로", 같은 자기 진행상황·옵션 안내 일절 X. 첫 줄부터 본문 시작.

다음을 자연스럽게 녹여서:
1. 한 줄 요약 — 오늘이 어떤 하루였는지
2. 주제·테마 — 반복 등장한 키워드·관심사
3. 발견·관찰 — 흥미로운 패턴 또는 환기할 만한 것
4. (있으면) ⚠️ **펜딩 환기** — 며칠째 무언급된 thread 목록을 마지막에 짧게 짚어줌 ("MX Master 4 thread 5일째 무언급 — 마무리됐나요?")
5. (있으면) 👍 **취향 신호 메모** — 사용자가 useful/interesting 표시한 항목들의 공통점

마크다운 본문(상위 헤더는 호출자가 # 날짜로 붙임). 친근하고 간결한 한국어. 짧은 리스트 OK.
정본 평문은 corpus/에 그대로 있고, 이건 그 위의 닫힌 다이제스트."""


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

    # 6) 상위 인덱스 갱신 (코드 aggregate, vault master.md + MongoDB index_meta)
    idx = _update_master_index(target)
    result["index"] = idx

    return result


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
        f"## 오늘({target.isoformat()}) 기록 ({len(records)}건)",
        json.dumps(_records_brief(records), ensure_ascii=False, indent=2),
    ]
    if silent_threads:
        parts.append(f"\n## ⚠️ 펜딩 환기 후보 (며칠째 무언급 — 다이제스트 마지막에 부드럽게 짚어주기)")
        parts.append(json.dumps(silent_threads, ensure_ascii=False, indent=2))
    if reactions and sum(reactions.values()) > 0:
        parts.append(f"\n## 👍 오늘의 이모지 반응 집계")
        parts.append(json.dumps(reactions, ensure_ascii=False))
        parts.append("(useful/interesting로 표시된 항목들의 공통점을 메모에 살짝)")
    prompt = "\n".join(parts) + "\n\n위 정보로 오늘의 다이제스트를 작성."
    try:
        r = nest_client.call(alias=alias, prompt=prompt, system=DAILY_DIGEST_SYSTEM)
        body = (r.get("text") or "").strip()
        return f"# {target.isoformat()}\n\n{body}\n"
    except Exception as e:
        return f"# {target.isoformat()}\n\n(digest 생성 실패: {e})\n"


def _aggregate_reactions(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """그 날 record들의 이모지 반응 집계 (취향 신호)."""
    counts = {"interesting": 0, "useful": 0, "skip": 0}
    for r in records:
        rxn = r.get("reaction")
        if rxn in counts:
            counts[rxn] += 1
    return counts


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
