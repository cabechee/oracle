"""MongoDB — 인덱스/메타데이터 저장소.

정본은 vault(평문)에 있고, MongoDB는 검색·thread·index 메타용.
MongoDB가 손실돼도 vault에서 재생성 가능한 캐시 성격.

컬렉션:
- records:    한 캡처 단위 (사진+코멘트+VLM+LLM즉답 + 자정 부착물)
- threads:    여러 Record를 잇는 정체성 (자정에 LLM이 부착)
- index_meta: 월별 태그/엔티티/thread 활동 가벼운 구조 (자정 갱신)
- journals:   일/주/월 서술 저널 (semantic 계층, 자정·주·월 배치가 생성 + 임베딩)
              _id = "day-YYYY-MM-DD" | "week-YYYY-Www" | "month-YYYY-MM"
"""

from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from config import MONGO_URL, MONGO_DB


_client: Optional[MongoClient] = None


def _conn() -> Database:
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URL)
    return _client[MONGO_DB]


def records() -> Collection:
    return _conn().records


def threads() -> Collection:
    return _conn().threads


def index_meta() -> Collection:
    return _conn().index_meta


def journals() -> Collection:
    return _conn().journals


def ensure_indexes() -> None:
    """1회 호출 — Mongo가 idempotent하게 인덱스 생성."""
    try:
        records().create_index("ts")
        records().create_index("thread_ids")
        threads().create_index("status")
        journals().create_index("kind")
        journals().create_index("period_start")
    except Exception:
        # MongoDB가 안 떠 있어도 import는 통과 (api/ingest 호출 시 fail)
        pass
