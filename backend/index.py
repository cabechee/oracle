"""상위 인덱스 — 월별 통계(MongoDB index_meta) + vault index/master.md.

LLM 없이 코드 aggregate. 자정 배치가 매일 갱신(idempotent).
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional
from pathlib import Path

import db
from config import VAULT_DIR


def update_master_index(target: date) -> Dict[str, Any]:
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
