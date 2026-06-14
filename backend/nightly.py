"""자정 배치 오케스트레이션 — Layer 3.

run_nightly: 어제 일 저널 + (월요일)주간 + (1일)월간. 한 cron으로 일/주/월 처리.
run_daily: 분류(thread/type) → reaction 집계 → 일 저널 생성·저장 → 상위 인덱스 갱신.

수동 트리거: POST /digest/run?target_date=YYYY-MM-DD (안 주면 어제).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional

import db
import threads as threads_mod
import classify
import journal
import signals as signals_mod
import index as index_mod


def run_nightly() -> Dict[str, Any]:
    """자정 plist가 호출(target 없음). 어제 일 저널 + (월요일이면)주간 + (1일이면)월간.

    한 cron으로 일/주/월을 모두 처리 — 추가 launchd 불필요. 각 단계 독립 try.
    """
    out: Dict[str, Any] = {}
    out["daily"] = run_daily(None)
    today = date.today()
    if today.weekday() == 0:   # 월요일 = 지난 주(월~일) 완료
        try:
            out["weekly"] = journal.run_weekly()
        except Exception as e:
            out["weekly"] = {"ok": False, "error": str(e)}
    if today.day == 1:         # 매월 1일 = 지난 달 완료
        try:
            out["monthly"] = journal.run_monthly()
        except Exception as e:
            out["monthly"] = {"ok": False, "error": str(e)}
    return out


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
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_thread = ex.submit(classify.judge_threads, records)
        f_type = ex.submit(classify.classify_type_tags, records)
        thread_res = (f_thread.result() or {})
        type_res = (f_type.result() or {})

    for a in thread_res.get("assignments", []) or []:
        if not isinstance(a, dict):
            continue
        rid = a.get("record_id")
        raw_tids = a.get("thread_ids") or []
        tids: list = []
        for t in (raw_tids if isinstance(raw_tids, list) else []):
            # threads._id 는 int — 문자열 id가 섞이면 메타 조회·집계가 어긋남(new_threads와 동일 가드)
            try:
                tids.append(int(t))
            except (TypeError, ValueError):
                print(f"[nightly] thread_id 비정수 — 무시: {t!r} (record {rid})", flush=True)
        if rid:
            db.records().update_one({"_id": rid}, {"$set": {"thread_ids": tids}})
    for nt in thread_res.get("new_threads", []) or []:
        if not isinstance(nt, dict):
            continue
        tid = nt.get("id")
        if tid is None:
            continue
        try:
            threads_mod.upsert_thread(
                int(tid), nt.get("name", f"thread-{tid}"), nt.get("lineage_from"))
        except (TypeError, ValueError):
            # LLM이 비정수 id를 내도 그 항목만 버리고 배치는 계속
            print(f"[nightly] new_thread id 비정수 — 무시: {nt!r}", flush=True)
    result["thread_assignments"] = len(thread_res.get("assignments", []) or [])
    result["new_threads"] = len(thread_res.get("new_threads", []) or [])

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
    reactions = journal.aggregate_reactions(records)
    result["reactions"] = reactions

    # 4) silent threads (펜딩 환기 후보) — 3~30일 무언급
    silent = threads_mod.silent_threads(min_days=3, max_days=30)
    result["silent_thread_count"] = len(silent)

    # 4.5) 그날 받은 연락(문자·부재중, 비-OTP) — 일기의 배경 재료
    day_signals = signals_mod.signals_for_day(target)
    result["signal_count"] = len(day_signals)

    # 5) 일 저널 (LLM, silent + reactions + signals 포함된 풍부한 prompt) → vault digest + journals
    digest_text = journal.make_daily_journal(records, target, silent, reactions, day_signals)
    result["digest_path"] = journal.write_daily_digest_file(target, digest_text)
    result["digest_preview"] = digest_text[:200]
    summary3 = journal.make_day_summary3(digest_text)
    result["day_summary3"] = summary3
    result["journal_embedded"] = journal.save_day_journal(
        target, digest_text, len(records), reactions, start, end, summary3=summary3)

    # 6) 상위 인덱스 갱신 (코드 aggregate, vault master.md + MongoDB index_meta)
    result["index"] = index_mod.update_master_index(target)

    return result
