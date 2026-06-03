"""환경 설정 — env로 오버라이드 가능.

핵심: Nest 게이트웨이 주소/토큰 + task→alias 매핑 + MongoDB + vault 경로.
비밀(토큰)은 .env(gitignored)에만 — 코드/커밋에 박지 않는다.
"""

import os

try:
    from dotenv import load_dotenv
    # 프로젝트 루트(backend의 한 단계 위)의 .env 로드
    _root_env = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".env",
    )
    load_dotenv(_root_env)
except ImportError:
    pass


# ── Nest 게이트웨이 ─────────────────────────────────────────────
NEST_BASE_URL = os.getenv("NEST_BASE_URL", "http://192.168.68.50:7780")
NEST_TOKEN = os.getenv("NEST_TOKEN", "")
NEST_TIMEOUT = int(os.getenv("NEST_TIMEOUT", "300"))


# ── Task → Nest alias 매핑 ──────────────────────────────────────
# 디폴트 = "" (env override 없으면 빈 값). 빈 값이면 ingest가 Nest에 등록된
# enabled 모델 중 첫 모델을 자동 선택 — Nest에 모델 추가/제거 즉시 반영.
# 특정 task에 모델 고정하려면 .env에 ORACLE_VLM=xxx 같이 명시.
TASK_ALIAS = {
    # Layer 1 (인입 시점, 즉시)
    "vlm_caption":   os.getenv("ORACLE_VLM",     ""),
    "insight":       os.getenv("ORACLE_INSIGHT", ""),
    # Layer 3 (자정 배치) — 슬라이스 다음 단계에서 사용
    "type_classify": os.getenv("ORACLE_TYPE",    ""),
    "thread_judge":  os.getenv("ORACLE_THREAD",  ""),
    "daily_digest":  os.getenv("ORACLE_DIGEST",  ""),
    "index_update":  os.getenv("ORACLE_INDEX",   ""),
    "query":         os.getenv("ORACLE_QUERY",   ""),
}


# ── MongoDB ─────────────────────────────────────────────────────
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "oracle")


# ── 정본 Vault 경로 ─────────────────────────────────────────────
_default_vault = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "corpus",
)
VAULT_DIR = os.getenv("VAULT_DIR", _default_vault)


# ── 서버 ────────────────────────────────────────────────────────
HOST = os.getenv("ORACLE_HOST", "0.0.0.0")
PORT = int(os.getenv("ORACLE_PORT", "8001"))   # finder=8000 옆 (8765=claude-dashboard 차지, 회피)
