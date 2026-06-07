"""agent.memory — 계층적 기억 검색·주입.

리서치(memory-hierarchy) 결론 반영:
- 검색은 관련도(임베딩)만으로 하지 않는다. Generative Agents의 **3요소 가중 스코어**:
  similarity(임베딩 코사인) + recency(시간 지수감쇠) + importance(reaction 신호).
- 검색 소스는 **일 저널(semantic, 거시 맥락) + 개별 record(episodic, 미시 사실)** 합집합.
  저널은 자정 배치가 서술로 만든 의미 계층, record는 캡처 단위 원본.

graceful: 임베딩 alias 미설정/Nest 실패/임베딩된 후보 없음/차원 불일치 → None
          (호출자가 최근순 fallback).
"""

import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Sequence

import db
import embedding as embedding_mod
from config import (
    MEMORY_W_SIM,
    MEMORY_W_RECENCY,
    MEMORY_W_IMPORTANCE,
    MEMORY_RECENCY_TAU_DAYS,
    WORKING_MEMORY_DAYS,
)


# reaction → record 중요도 스칼라 (정규화 전 raw). none=중립 baseline.
_REACTION_IMPORTANCE = {"useful": 1.0, "interesting": 0.8, "skip": 0.0}
_IMPORTANCE_BASELINE = 0.4


def _recency(ts: Any, now: datetime, tau_days: float) -> float:
    """경과일 기준 지수감쇠. ts가 datetime 아니면 0."""
    if not hasattr(ts, "timestamp"):
        return 0.0
    days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return math.exp(-days / max(1e-6, tau_days))


def _record_importance(rec: Dict[str, Any]) -> float:
    return _REACTION_IMPORTANCE.get(rec.get("reaction"), _IMPORTANCE_BASELINE)


def _journal_importance(j: Dict[str, Any]) -> float:
    """저널은 그 기간의 reaction 집계로 중요도. 신호 많을수록 높게(상한 1)."""
    rs = j.get("reaction_signal") or {}
    raw = _IMPORTANCE_BASELINE + 0.12 * (rs.get("useful") or 0) + 0.08 * (rs.get("interesting") or 0)
    return min(1.0, raw)


def _minmax(vals: Sequence[float]) -> List[float]:
    """후보 집합 안에서 [0,1] 정규화. 전부 동일하면 중립 0.5."""
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return [0.5 for _ in vals]
    return [(v - lo) / (hi - lo) for v in vals]


def search(
    question: str,
    top_k: int = 12,
    kinds: Sequence[str] = ("journal", "record"),
) -> Optional[List[Dict[str, Any]]]:
    """질문 임베딩 → 저널+record 후보에 3요소 스코어 top_k.

    반환: [{id, kind, ts, score, sim, recency, importance, (저널이면 date)}], 점수 내림차순.
    None = 검색 불가 → 호출자가 최근순 fallback.
    """
    qe = embedding_mod.embed_text(question)
    if not qe:
        return None
    try:
        import numpy as np
    except ImportError:
        return None

    q = np.asarray(qe["embedding"], dtype="float32")
    if q.ndim != 1:
        return None
    qn = q / (np.linalg.norm(q) + 1e-8)
    qdim = int(q.shape[0])

    now = datetime.now()
    cands: List[Dict[str, Any]] = []

    if "record" in kinds:
        cur = db.records().find(
            {"embedding": {"$exists": True, "$ne": None}},
            {"_id": 1, "embedding": 1, "ts": 1, "reaction": 1},
        )
        for d in cur:
            v = d.get("embedding")
            if not v or len(v) != qdim:
                continue
            cands.append({
                "id": d["_id"],
                "kind": "record",
                "ts": d.get("ts"),
                "vec": v,
                "importance": _record_importance(d),
            })

    if "journal" in kinds:
        cur = db.journals().find(
            {"kind": "day", "embedding": {"$exists": True, "$ne": None}},
            {"_id": 1, "embedding": 1, "period_end": 1, "period_start": 1,
             "date": 1, "reaction_signal": 1},
        )
        for j in cur:
            v = j.get("embedding")
            if not v or len(v) != qdim:
                continue
            cands.append({
                "id": j["_id"],
                "kind": "journal",
                "ts": j.get("period_end") or j.get("period_start"),
                "vec": v,
                "importance": _journal_importance(j),
                "date": j.get("date"),
            })

    if not cands:
        return None

    mat = np.asarray([c["vec"] for c in cands], dtype="float32")
    if mat.ndim != 2 or mat.shape[1] != qdim:
        return None
    mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    sims = (mat_n @ qn).tolist()
    recs = [_recency(c["ts"], now, MEMORY_RECENCY_TAU_DAYS) for c in cands]
    imps = [c["importance"] for c in cands]

    # 각 요소 후보집합 내 정규화 (유사도는 음수 절단 후)
    sim_n = _minmax([max(0.0, s) for s in sims])
    rec_n = _minmax(recs)
    imp_n = _minmax(imps)

    scored: List[Dict[str, Any]] = []
    for i, c in enumerate(cands):
        score = (
            MEMORY_W_SIM * sim_n[i]
            + MEMORY_W_RECENCY * rec_n[i]
            + MEMORY_W_IMPORTANCE * imp_n[i]
        )
        item = {k: v for k, v in c.items() if k != "vec"}
        item["score"] = score
        item["sim"] = float(sims[i])
        item["recency"] = float(recs[i])
        item["importance"] = float(imps[i])
        ts = item.get("ts")
        if hasattr(ts, "isoformat"):
            item["ts"] = ts.isoformat()
        scored.append(item)

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


# ── 워킹 메모리 (즉답 인사이트 주입) ──────────────────────────

def working_memory(now: Optional[datetime] = None, days: Optional[int] = None) -> str:
    """즉답 인사이트용 워킹 컨텍스트 = 지난 N일 일 저널(서술) + 오늘 raw 캡처(시간순).

    동반자가 며칠 흐름을 기억하도록 항상 주입(`_recent_context` 대체).
    이 블록은 캡처마다 거의 고정 → 캐싱(M6) 대상 prefix 후보.
    days<=0 또는 자료 없음이면 빈 문자열(graceful).
    """
    now = now or datetime.now()
    days = WORKING_MEMORY_DAYS if days is None else days
    if days <= 0:
        return ""
    today_start = datetime(now.year, now.month, now.day)
    window_start = today_start - timedelta(days=days)
    parts: List[str] = []

    # 1) 지난 N일 일 저널 (오름차순). 오늘 저널은 아직 없음(자정 생성).
    jcur = db.journals().find(
        {"kind": "day", "period_start": {"$gte": window_start, "$lt": today_start}},
        {"_id": 1, "date": 1, "text": 1, "period_start": 1},
    ).sort("period_start", 1)
    jblocks: List[str] = []
    for j in jcur:
        t = (j.get("text") or "").strip()
        if not t:
            continue
        # 저장된 text는 보통 '# 날짜' 헤더로 시작 — 없으면 날짜 헤더를 붙여준다.
        jblocks.append(t if t.lstrip().startswith("#") else f"## {j.get('date', '')}\n{t}")
    if jblocks:
        parts.append("[지난 며칠의 일기]\n" + "\n\n".join(jblocks))

    # 2) 오늘 raw 캡처 (시간순)
    rcur = db.records().find(
        {"ts": {"$gte": today_start, "$lt": now}},
        {"user_comment": 1, "insight": 1, "ts": 1},
    ).sort("ts", 1)
    lines: List[str] = []
    for r in rcur:
        ts = r.get("ts")
        tstr = ts.strftime("%H:%M") if hasattr(ts, "strftime") else ""
        c = (r.get("user_comment") or "").strip()
        ins = ((r.get("insight") or {}).get("text") or "").strip()
        seg: List[str] = []
        if c:
            seg.append(f"유저: {c}")
        if ins:
            seg.append(f"나: {ins[:160]}")
        if seg:
            lines.append(f"[{tstr}] " + " / ".join(seg))
    if lines:
        parts.append("[오늘 (시간순)]\n" + "\n".join(lines))

    return "\n\n".join(parts)
