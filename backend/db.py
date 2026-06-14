"""MongoDB — 인덱스/메타데이터 저장소.

정본은 vault(평문)에 있고, MongoDB는 검색·thread·index 메타용.
MongoDB가 손실돼도 vault에서 재생성 가능한 캐시 성격.

컬렉션:
- records:    한 캡처 단위 (사진+코멘트+VLM+LLM즉답 + 자정 부착물)
- threads:    여러 Record를 잇는 정체성 (자정에 LLM이 부착)
- index_meta: 월별 태그/엔티티/thread 활동 가벼운 구조 (자정 갱신)
- journals:   일/주/월 서술 저널 (semantic 계층, 자정·주·월 배치가 생성 + 임베딩)
              _id = "day-YYYY-MM-DD" | "week-YYYY-Www" | "month-YYYY-MM"
- conversations: 대화 모드 메시지 (role=user|assistant, ts 순 타임라인)
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


def conversations() -> Collection:
    return _conn().conversations


def signals() -> Collection:
    """수동 신호 원본 (SMS·부재중·알림) — record와 분리된 스트림, 패턴 창발용."""
    return _conn().signals


def signal_briefs() -> Collection:
    """신호 요약본 (30분 주기) — 앱 알림으로 나간 brief 이력."""
    return _conn().signal_briefs


def settings() -> Collection:
    """런타임 설정 — personas override 등 (어드민 편집). _id로 문서 구분."""
    return _conn().settings


def metrics() -> Collection:
    """일별 건강 지표 (수면·걸음) — _id=날짜(YYYY-MM-DD). 홈 표지·조간 재료."""
    return _conn().metrics


def briefings() -> Collection:
    """발행물 — 조간·석간 (_id=morning|evening-YYYY-MM-DD). 베르가 cron으로 합성."""
    return _conn().briefings


def dashboard_state() -> Collection:
    """데스크 항목 처리 상태 — _id=항목 키('action:...'|'pending:...'),
    dismissed_at 채워지면 '확인됨'으로 데스크에서 제외. 데스크=온라인 오라클."""
    return _conn().dashboard_state


def ledger() -> Collection:
    """가계부 — 결제 알림에서 뽑은 지출 (_id=pay-<signal>, 멱등). 스마트 액션."""
    return _conn().ledger


def reminders() -> Collection:
    """자체 리마인더 — 외부 연동 없이 앱 내부. 수동 추가 + action_needed 승격."""
    return _conn().reminders


def ensure_indexes() -> None:
    """1회 호출 — Mongo가 idempotent하게 인덱스 생성."""
    try:
        records().create_index("ts")
        records().create_index("thread_ids")
        threads().create_index("status")
        journals().create_index("kind")
        journals().create_index("period_start")
        conversations().create_index("ts")
        signals().create_index("ts")
        signals().create_index("kind")
        signal_briefs().create_index("ts")
    except Exception:
        # MongoDB가 안 떠 있어도 import는 통과 (api/ingest 호출 시 fail)
        pass
