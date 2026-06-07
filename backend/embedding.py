"""record 임베딩 — 검색 텍스트 빌드 + Nest 임베딩 생성 + Mongo 저장/brute-force 검색.

설계:
- 임베딩 생성은 Nest 게이트웨이(ORACLE_EMBED alias) 경유 — 모든 모델 호출 일원화 + 비용 로깅.
- 벡터는 records.embedding(float 배열)에 저장. 개인 규모라 brute-force 코사인(numpy)으로 충분.
- 전부 graceful: alias 미설정 / Nest 실패 / 빈 텍스트면 조용히 skip → 검색은 최근순 fallback.
- 모델/차원 agnostic: 응답 dims 를 그대로 저장(고정 안 함). 차원 바뀌면 검색이 자동 fallback.
"""

from typing import Optional, List, Dict, Any, Tuple

import nest_client
import db
from config import TASK_ALIAS


def embed_alias() -> str:
    """임베딩 전용 alias. 비어 있으면 임베딩 비활성(chat alias로 fallback하지 않음)."""
    return TASK_ALIAS.get("embed") or ""


def build_text(rec: Dict[str, Any]) -> str:
    """record 의 검색 대상 텍스트 = 유저 코멘트 + VLM 묘사 + LLM 인사이트 + 태그."""
    parts: List[str] = []
    if rec.get("user_comment"):
        parts.append(str(rec["user_comment"]))
    cap = (rec.get("vlm") or {}).get("caption")
    if cap:
        parts.append(str(cap))
    ins = (rec.get("insight") or {}).get("text")
    if ins:
        parts.append(str(ins))
    sug = rec.get("suggestion")
    if sug:
        parts.append(str(sug))
    au = (rec.get("audio") or {}).get("caption")
    if au:
        parts.append(str(au))
    tags = rec.get("tags") or []
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    return "\n".join(parts).strip()


def embed_record(record_id: str, rec: Optional[Dict[str, Any]] = None) -> bool:
    """record 한 건 임베딩 → records.embedding 갱신.

    alias 미설정 · 빈 텍스트 · Nest 실패면 False(저장 안 함, 예외 전파 안 함).
    """
    alias = embed_alias()
    if not alias:
        return False
    if rec is None:
        rec = db.records().find_one({"_id": record_id})
        if not rec:
            return False
    text = build_text(rec)
    if not text:
        return False
    try:
        data = nest_client.embed(alias, [text])
    except Exception:
        return False
    vecs = data.get("embeddings") or []
    if not vecs or not vecs[0]:
        return False
    db.records().update_one(
        {"_id": record_id},
        {"$set": {
            "embedding": vecs[0],
            "embed_meta": {
                "alias": alias,
                "model": data.get("model"),
                "dims": data.get("dims"),
            },
        }},
    )
    return True


def embed_text(text: str) -> Optional[Dict[str, Any]]:
    """임의 텍스트 임베딩 → {embedding, embed_meta} 또는 None(graceful).

    journals 등 record 아닌 대상에 임베딩을 붙일 때 공용으로 사용.
    """
    alias = embed_alias()
    if not alias or not (text or "").strip():
        return None
    try:
        data = nest_client.embed(alias, [text])
    except Exception:
        return None
    vecs = data.get("embeddings") or []
    if not vecs or not vecs[0]:
        return None
    return {
        "embedding": vecs[0],
        "embed_meta": {
            "alias": alias,
            "model": data.get("model"),
            "dims": data.get("dims"),
        },
    }


def embed_journal(journal_id: str, text: str) -> bool:
    """journals 문서 한 건에 임베딩 부착 (graceful)."""
    e = embed_text(text)
    if not e:
        return False
    db.journals().update_one({"_id": journal_id}, {"$set": e})
    return True


def search(question: str, top_k: int = 12) -> Optional[List[Tuple[str, float]]]:
    """질문 임베딩 → embedding 보유 record 와 brute-force 코사인 top_k.

    반환: [(record_id, score), ...] 점수 내림차순.
    None = 임베딩 검색 불가(alias 미설정 / Nest 실패 / 임베딩된 record 없음 / 차원 불일치)
           → 호출자가 최근순 fallback.
    """
    alias = embed_alias()
    if not alias:
        return None
    try:
        qv = nest_client.embed_one(alias, question)
    except Exception:
        return None
    if not qv:
        return None
    try:
        import numpy as np
    except ImportError:
        return None

    docs = list(db.records().find(
        {"embedding": {"$exists": True, "$ne": None}},
        {"_id": 1, "embedding": 1},
    ))
    if not docs:
        return None
    try:
        mat = np.asarray([d["embedding"] for d in docs], dtype="float32")
        q = np.asarray(qv, dtype="float32")
    except Exception:
        return None
    # 차원 불일치(모델 교체 등) — 안전하게 fallback
    if mat.ndim != 2 or q.ndim != 1 or mat.shape[1] != q.shape[0]:
        return None

    mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    qn = q / (np.linalg.norm(q) + 1e-8)
    sims = mat_n @ qn

    k = min(top_k, len(docs))
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [(docs[i]["_id"], float(sims[i])) for i in idx]


def backfill(limit: Optional[int] = None) -> Dict[str, Any]:
    """embedding 없는 기존 record 일괄 임베딩(건당 호출). 마이그레이션/운영용.

    limit 지정 시 그만큼만 처리(여러 번 나눠 돌릴 수 있음).
    """
    alias = embed_alias()
    if not alias:
        return {"ok": False, "reason": "embed alias 미설정 (ORACLE_EMBED)"}
    cur = db.records().find({"embedding": {"$exists": False}})
    if limit:
        cur = cur.limit(limit)
    embedded = skipped = 0
    for rec in cur:
        if embed_record(rec["_id"], rec):
            embedded += 1
        else:
            skipped += 1
    return {"ok": True, "embedded": embedded, "skipped": skipped, "alias": alias}
