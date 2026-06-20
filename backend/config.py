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
    # 빠른 1차 반응 — 쿠키(오목눈이). 모든 캡처가 메인(베르) 전에 이걸 먼저 거침.
    # 짧은 첫인상 한마디. 텍스트·사진은 quick, 영상·음성이 끼면 멀티모달 quick_av.
    # 코멘트 품질이 중요하니 여기에 좋은 모델을 둔다. 빈 값이면 쿠키 skip.
    "quick":         os.getenv("ORACLE_QUICK",    "gemini"),
    "quick_av":      os.getenv("ORACLE_QUICK_AV", "gemini-flash"),
    "vlm_caption":   os.getenv("ORACLE_VLM",     ""),
    # 텍스트·소리 캡처 즉답 (베르)
    "insight":       os.getenv("ORACLE_INSIGHT", ""),
    # 사진 분석·코멘트 (베르) — 빈 값이면 insight로 폴백
    "vision":        os.getenv("ORACLE_VISION",  ""),
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
    # 대화 모드 (히스토리 탭 채팅). 빈 값이면 query → Nest 첫 모델 순 fallback.
    "chat":          os.getenv("ORACLE_CHAT",    ""),
    # 신호(SMS·부재중) 요약 — ⚠️ 반드시 로컬 alias만(qwen-vlm 등). SMS 본문은
    # 클라우드로 보내지 않는다(사용자 결정 2026-06-11). 빈 값이면 저장만 하고 요약 skip.
    "signals":       os.getenv("ORACLE_SIGNALS", ""),
}


# task별 모델 alias — settings.task_aliases(어드민에서 직접 선택) override > env(TASK_ALIAS) > "".
# 페르소나처럼 5초 캐시(어드민 변경 즉시 반영). db는 순환 import 회피 위해 함수 내 lazy import.
_alias_cache = {}
_alias_cache_ts = 0.0


def task_alias(key: str) -> str:
    """용도(key)별 현재 적용 모델 alias. 어드민 override가 있으면 그것, 없으면 env 디폴트."""
    global _alias_cache, _alias_cache_ts
    import time
    now = time.time()
    if now - _alias_cache_ts > 5:
        try:
            import db as _db
            _alias_cache = _db.settings().find_one({"_id": "task_aliases"}) or {}
        except Exception:
            _alias_cache = {}
        _alias_cache_ts = now
    ov = _alias_cache.get(key)
    if isinstance(ov, str) and ov.strip():
        return ov.strip()
    return TASK_ALIAS.get(key) or ""


# ── 메모리 검색 3요소 스코어 (Generative Agents식) ───────────────
# 검색 점수 = W_SIM·유사도 + W_RECENCY·최근성(지수감쇠) + W_IMPORTANCE·중요도(reaction).
# 각 요소는 후보 집합 안에서 min-max 정규화 후 가중합. 가중치 0이면 그 요소 무시.
# TAU_DAYS = 최근성 감쇠 시정수(클수록 과거를 덜 깎음). 일상 캡처 빈도에 맞춰 튜닝.
MEMORY_W_SIM = float(os.getenv("ORACLE_MEM_W_SIM", "1.0"))
MEMORY_W_RECENCY = float(os.getenv("ORACLE_MEM_W_RECENCY", "1.0"))
MEMORY_W_IMPORTANCE = float(os.getenv("ORACLE_MEM_W_IMPORTANCE", "1.0"))
MEMORY_RECENCY_TAU_DAYS = float(os.getenv("ORACLE_MEM_TAU_DAYS", "30"))

# 워킹 메모리(즉답 인사이트·대화에 주입) — 지난 N일 일 저널 + 오늘 raw 캡처. (M3)
# 이게 "채팅처럼 자연스럽게 유지되는 컨텍스트". 검색 candidate 대신 이걸 주 기억으로 써서
# 억지 연결을 막는다(2026-06-13). 0이면 비활성. .env(ORACLE_WORKING_DAYS)로 조절.
WORKING_MEMORY_DAYS = int(os.getenv("ORACLE_WORKING_DAYS", "7"))

# 워킹 메모리 문자 상한 — 저널이 쌓여도 캡처당 주입 토큰이 무한 증가하지 않게.
# 최신 날짜부터 채우고 오래된 날짜를 버린다. 0이면 무제한(기존 동작).
WORKING_MEMORY_MAX_CHARS = int(os.getenv("ORACLE_WORKING_MAX_CHARS", "12000"))


# 임베딩 직결 모드(우회) — OpenAI 호환 /v1/embeddings 엔드포인트 URL.
# 설정 시 임베딩만 Nest를 거치지 않고 이 서버로 직접 호출 (chocolat 라이브 Nest에
# /api/embed 미배포 동안의 임시 경로). 비우면 Nest /api/embed 경유(원래 설계).
EMBED_DIRECT_URL = os.getenv("ORACLE_EMBED_URL", "")


# ── MongoDB ─────────────────────────────────────────────────────
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "oracle")


# ── 정본 Vault 경로 ─────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_default_vault = os.path.join(_PROJECT_ROOT, "corpus")
VAULT_DIR = os.getenv("VAULT_DIR", _default_vault)


# ── Google Workspace (캘린더) ───────────────────────────────────
# OAuth2 Installed/Desktop 앱. credentials.json(클라이언트)·token.json(동의 후) 모두
# 프로젝트 루트(.env 옆, gitignored). 인증은 scripts/gcal_auth.py 1회. 비밀은 커밋 금지.
GCAL_CREDS_PATH = os.getenv(
    "GCAL_CREDS_PATH", os.path.join(_PROJECT_ROOT, "gcal_credentials.json"))
GCAL_TOKEN_PATH = os.getenv(
    "GCAL_TOKEN_PATH", os.path.join(_PROJECT_ROOT, "gcal_token.json"))
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary")


# ── Tesla Fleet API (차량 위치·운행 — 차 상태머신 보강) ─────────────
# 비밀(client secret)은 .env에만. developer.tesla.com 폼 완료 후 발급받아 채운다.
# 지역 베이스: 한국=아태권은 NA 엔드포인트. EU/중국이면 .env에서 TESLA_API_BASE 교체.
TESLA_CLIENT_ID = os.getenv("TESLA_CLIENT_ID", "")
TESLA_CLIENT_SECRET = os.getenv("TESLA_CLIENT_SECRET", "")
TESLA_DOMAIN = os.getenv("TESLA_DOMAIN", "oraclecar.pages.dev")
TESLA_REDIRECT_URI = os.getenv("TESLA_REDIRECT_URI", "http://localhost:8080/callback")
TESLA_API_BASE = os.getenv(
    "TESLA_API_BASE", "https://fleet-api.prd.na.vn.cloud.tesla.com")
TESLA_SCOPES = os.getenv(
    "TESLA_SCOPES",
    "openid offline_access vehicle_device_data vehicle_location vehicle_charging_cmds")
TESLA_TOKEN_PATH = os.getenv(
    "TESLA_TOKEN_PATH", os.path.join(_PROJECT_ROOT, "tesla_token.json"))
TESLA_PRIVATE_KEY_PATH = os.getenv(
    "TESLA_PRIVATE_KEY_PATH", os.path.join(_PROJECT_ROOT, "tesla-private-key.pem"))
# 비용 가드 — 하루 테슬라 호출 상한(버그·루프 대비). 이벤트 전용이라 평소 ~수십 회 미만.
TESLA_DAILY_CAP = int(os.getenv("TESLA_DAILY_CAP", "50"))


# ── 서버 ────────────────────────────────────────────────────────
HOST = os.getenv("ORACLE_HOST", "0.0.0.0")
PORT = int(os.getenv("ORACLE_PORT", "8001"))   # finder=8000 옆 (8765=claude-dashboard 차지, 회피)

# API 토큰 (opt-in) — 설정하면 loopback 외 모든 요청에 X-Oracle-Token 헤더 요구.
# 폰 앱은 --dart-define=ORACLE_TOKEN=... 으로 빌드해야 함. 비우면 무인증(기존 동작).
ORACLE_TOKEN = os.getenv("ORACLE_TOKEN", "")
