"""FastAPI 라우터 — 도메인별 sub-router를 메인 router에 결합.

라우터는 얇게(요청 파싱 → 서비스 호출 → dict). 비즈니스 로직은 서비스 모듈에.
"""

from fastapi import APIRouter

from . import ingest, records, journal, threads, query, chat, index, nest, signals, home, admin, metrics, briefing, companion, dashboard

router = APIRouter()
router.include_router(ingest.router)
router.include_router(records.router)
router.include_router(journal.router)
router.include_router(threads.router)
router.include_router(query.router)
router.include_router(chat.router)
router.include_router(index.router)
router.include_router(nest.router)
router.include_router(signals.router)
router.include_router(home.router)
router.include_router(admin.router)
router.include_router(metrics.router)
router.include_router(briefing.router)
router.include_router(companion.router)
router.include_router(dashboard.router)
