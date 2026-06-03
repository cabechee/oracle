"""Thread 관리 — 정체성 닻.

각 thread = 여러 record를 잇는 명시적 연결(상태 X, 정체성만).
ingest 시점엔 thread 부착 X — 자정 배치(digest.run_daily)가 LLM으로 판정 후 부착.

silent_threads = "5일째 무언급" 같은 펜딩 환기 후보.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import db


def list_active_threads(within_days: int = 60) -> List[Dict[str, Any]]:
    """최근 N일 안에 활동 있는 thread 목록 (last_seen 내림차순)."""
    cutoff = datetime.now() - timedelta(days=within_days)
    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}, "thread_ids": {"$ne": []}}},
        {"$unwind": "$thread_ids"},
        {"$group": {
            "_id": "$thread_ids",
            "last_seen": {"$max": "$ts"},
            "record_count": {"$sum": 1},
        }},
        {"$sort": {"last_seen": -1}},
    ]
    out: List[Dict[str, Any]] = []
    for item in db.records().aggregate(pipeline):
        tid = item["_id"]
        meta = db.threads().find_one({"_id": tid}) or {}
        ls = item.get("last_seen")
        out.append({
            "id": tid,
            "name": meta.get("name", f"thread-{tid}"),
            "lineage_from": meta.get("lineage_from"),
            "last_seen": ls.isoformat() if hasattr(ls, "isoformat") else ls,
            "record_count": item.get("record_count", 0),
        })
    return out


def get_thread(thread_id: int) -> Optional[Dict[str, Any]]:
    meta = db.threads().find_one({"_id": thread_id})
    if not meta:
        return None
    last = db.records().find_one({"thread_ids": thread_id}, sort=[("ts", -1)])
    count = db.records().count_documents({"thread_ids": thread_id})
    created = meta.get("created_at")
    last_ts = last.get("ts") if last else None
    return {
        "id": thread_id,
        "name": meta.get("name", f"thread-{thread_id}"),
        "lineage_from": meta.get("lineage_from"),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "last_seen": last_ts.isoformat() if hasattr(last_ts, "isoformat") else last_ts,
        "record_count": count,
    }


def list_thread_records(thread_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """한 thread에 속한 record들 (timeline)."""
    cur = db.records().find({"thread_ids": thread_id}).sort("ts", -1).limit(limit)
    out: List[Dict[str, Any]] = []
    for r in cur:
        if hasattr(r.get("ts"), "isoformat"):
            r["ts"] = r["ts"].isoformat()
        out.append(r)
    return out


def upsert_thread(thread_id: int, name: str, lineage_from: Optional[int] = None) -> None:
    db.threads().update_one(
        {"_id": thread_id},
        {
            "$set": {"name": name, "lineage_from": lineage_from},
            "$setOnInsert": {"created_at": datetime.now()},
        },
        upsert=True,
    )


def next_thread_id() -> int:
    """auto-increment thread id."""
    last = db.threads().find_one(sort=[("_id", -1)])
    return ((last and last.get("_id")) or 0) + 1


def silent_threads(min_days: int = 5, max_days: int = 30) -> List[Dict[str, Any]]:
    """min_days~max_days 동안 무언급된 thread (펜딩 환기 후보).
    너무 오래 지난 건 제외(max_days 안쪽만)."""
    now = datetime.now()
    cut_min = now - timedelta(days=min_days)
    cut_max = now - timedelta(days=max_days)
    pipeline = [
        {"$match": {"thread_ids": {"$ne": []}}},
        {"$unwind": "$thread_ids"},
        {"$group": {"_id": "$thread_ids", "last_seen": {"$max": "$ts"}}},
        {"$match": {"last_seen": {"$lt": cut_min, "$gte": cut_max}}},
        {"$sort": {"last_seen": 1}},
    ]
    out: List[Dict[str, Any]] = []
    for item in db.records().aggregate(pipeline):
        meta = db.threads().find_one({"_id": item["_id"]}) or {}
        ls = item["last_seen"]
        out.append({
            "id": item["_id"],
            "name": meta.get("name", f"thread-{item['_id']}"),
            "last_seen": ls.isoformat() if hasattr(ls, "isoformat") else ls,
            "days_silent": (now - ls).days if hasattr(ls, "isoformat") else None,
        })
    return out
