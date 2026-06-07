"""자연어 검색·질의 + 임베딩 backfill 라우터."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import query as query_mod
import embedding as embedding_mod

router = APIRouter()


class QueryReq(BaseModel):
    question: str
    limit: int = 30


@router.post("/query")
def ep_query(body: QueryReq):
    """자연어 질문 → LLM이 vault·records·인덱스 보고 답변 + 참조 record_id."""
    if not body.question.strip():
        raise HTTPException(400, "question 비어있음")
    try:
        return query_mod.query(body.question.strip(), body.limit)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/embed/backfill")
def ep_embed_backfill(limit: Optional[int] = None):
    """embedding 없는 기존 record 일괄 임베딩(운영/마이그레이션). ORACLE_EMBED 필요.

    limit 지정 시 그만큼만 처리(여러 번 나눠 실행 가능).
    """
    return embedding_mod.backfill(limit)
