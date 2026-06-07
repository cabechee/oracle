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
    # 검색 임베딩 (인입 시 record 부착 + 질의 시 질문 벡터화). Nest에 api 모델
    # (openai|openai_compat)을 'embed' alias로 등록. 빈 값이면 임베딩 비활성 → 최근순 검색.
    "embed":         os.getenv("ORACLE_EMBED",   ""),
    # 소리(오디오) 인식 — 인입 시 오디오를 인식하는 모델. 오디오 입력 가능 모델 권장(예: gemini).
    # 빈 값이면 오디오는 저장만 하고 인식 skip(graceful).
    "audio":         os.getenv("ORACLE_AUDIO",   ""),
    # Layer 3 (자정 배치) — 슬라이스 다음 단계에서 사용
    "type_classify": os.getenv("ORACLE_TYPE",    ""),
    "thread_judge":  os.getenv("ORACLE_THREAD",  ""),
    "daily_digest":  os.getenv("ORACLE_DIGEST",  ""),
    "weekly_journal":  os.getenv("ORACLE_WEEKLY",  ""),
    "monthly_journal": os.getenv("ORACLE_MONTHLY", ""),
    "index_update":  os.getenv("ORACLE_INDEX",   ""),
    "query":         os.getenv("ORACLE_QUERY",   ""),
}


# ── 인사이트 맥락 (메시지 간 연속성) ────────────────────────────
# insight 생성 시 최근 캡처를 맥락으로 주입 — 시간 윈도우(세션) + 개수 상한(토큰).
# CONTEXT_MAX=0 이면 맥락 비활성. .env(ORACLE_CONTEXT_MINUTES / ORACLE_CONTEXT_MAX)로 조절.
CONTEXT_MINUTES = int(os.getenv("ORACLE_CONTEXT_MINUTES", "30"))
CONTEXT_MAX = int(os.getenv("ORACLE_CONTEXT_MAX", "8"))


# ── 메모리 검색 3요소 스코어 (Generative Agents식) ───────────────
# 검색 점수 = W_SIM·유사도 + W_RECENCY·최근성(지수감쇠) + W_IMPORTANCE·중요도(reaction).
# 각 요소는 후보 집합 안에서 min-max 정규화 후 가중합. 가중치 0이면 그 요소 무시.
# TAU_DAYS = 최근성 감쇠 시정수(클수록 과거를 덜 깎음). 일상 캡처 빈도에 맞춰 튜닝.
MEMORY_W_SIM = float(os.getenv("ORACLE_MEM_W_SIM", "1.0"))
MEMORY_W_RECENCY = float(os.getenv("ORACLE_MEM_W_RECENCY", "1.0"))
MEMORY_W_IMPORTANCE = float(os.getenv("ORACLE_MEM_W_IMPORTANCE", "1.0"))
MEMORY_RECENCY_TAU_DAYS = float(os.getenv("ORACLE_MEM_TAU_DAYS", "30"))

# 워킹 메모리(즉답 인사이트에 주입) — 지난 N일 일 저널 + 오늘 raw 캡처. (M3)
# 0이면 비활성. .env(ORACLE_WORKING_DAYS)로 조절.
WORKING_MEMORY_DAYS = int(os.getenv("ORACLE_WORKING_DAYS", "30"))


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
