"""record/journal 임베딩 — 검색 텍스트 빌드 + Nest 임베딩 생성 + Mongo 저장.

설계:
- 임베딩 생성은 Nest 게이트웨이(ORACLE_EMBED alias) 경유 — 모든 모델 호출 일원화 + 비용 로깅.
- 벡터는 records/journals.embedding(float 배열)에 저장. 검색(코사인+3요소 스코어)은 agent.memory.
- 전부 graceful: alias 미설정 / Nest 실패 / 빈 텍스트면 조용히 skip → 검색은 최근순 fallback.
- 모델/차원 agnostic: 응답 dims 를 그대로 저장(고정 안 함). 차원 바뀌면 검색이 자동 fallback.
"""

from typing import Optional, List, Dict, Any

import db
from agent import llm
from config import task_alias


def embed_alias() -> str:
    """임베딩 전용 alias. 비어 있으면 임베딩 비활성(chat alias로 fallback하지 않음)."""
    return task_alias("embed") or ""


def build_text(rec: Dict[str, Any]) -> str:
    """record 의 검색 대상 텍스트 = 유저 코멘트 + VLM 묘사 + OCR 전문 + LLM 인사이트 + 태그."""
    parts: List[str] = []
    if rec.get("user_comment"):
        parts.append(str(rec["user_comment"]))
    cap = (rec.get("vlm") or {}).get("caption")
    if cap:
        parts.append(str(cap))
    # caption의 OCR은 150자 절단 — 영수증·문서 검색을 위해 분석 JSON의 전문도 포함
    ocr = str((rec.get("analysis") or {}).get("ocr_text") or "").strip()
    if ocr:
        parts.append(ocr)
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
        data = llm.embed(alias, [text])
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
        data = llm.embed(alias, [text])
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
