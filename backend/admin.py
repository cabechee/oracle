"""어드민 — 백엔드 데이터 전반 조회·관리 (개인 운영툴).

Mongo 컬렉션을 화이트리스트로 노출: 통계·목록·단건·삭제 + 신호 강제 요약.
Tailscale/loopback 경계로만 접근(토큰 미들웨어와 동일 보호). raw JSON 위주.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import db
import signals as signals_mod

# 노출 컬렉션 화이트리스트 — (라벨, 정렬키, 사진 미리보기 필드)
COLLECTIONS: Dict[str, Dict[str, Any]] = {
    "records":       {"label": "기록", "sort": "ts", "preview": "image_paths"},
    "journals":      {"label": "저널", "sort": "period_start", "preview": None},
    "briefings":     {"label": "발행물", "sort": "ts", "preview": None},
    "signals":       {"label": "신호 원본", "sort": "ts", "preview": None},
    "signal_briefs": {"label": "신호 요약", "sort": "ts", "preview": None},
    "threads":       {"label": "스레드", "sort": "last_ts", "preview": None},
    "conversations": {"label": "대화", "sort": "ts", "preview": None},
    "index_meta":    {"label": "인덱스", "sort": "_id", "preview": None},
}


def _coll(name: str):
    if name not in COLLECTIONS:
        raise ValueError(f"unknown collection: {name}")
    return db._conn()[name]


def _jsonable(v: Any) -> Any:
    """Mongo 문서를 JSON 직렬화 가능하게 — datetime→ISO, 중첩 재귀, 임베딩 축약."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, list):
        # 임베딩 등 큰 float 배열은 길이만 (어드민에 수백 차원 안 펼침)
        if len(v) > 32 and all(isinstance(x, (int, float)) for x in v[:4]):
            return f"<{len(v)}-dim vector>"
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def stats() -> Dict[str, Any]:
    """컬렉션별 카운트 + 최근 활동 타임스탬프."""
    out: List[Dict[str, Any]] = []
    for name, meta in COLLECTIONS.items():
        c = _coll(name)
        count = c.count_documents({})
        last = None
        sort_key = meta["sort"]
        doc = c.find_one(sort=[(sort_key, -1)]) if count else None
        if doc and isinstance(doc.get(sort_key), datetime):
            last = doc[sort_key].isoformat()
        out.append({"name": name, "label": meta["label"],
                    "count": count, "last": last})
    # 신호 미요약 수 — rebrief 버튼 노출용
    unbriefed = db.signals().count_documents(
        {"briefed": {"$ne": True}, "otp": {"$ne": True}})
    return {"collections": out, "unbriefed_signals": unbriefed}


def list_docs(name: str, limit: int = 50, skip: int = 0,
              q: Optional[str] = None) -> Dict[str, Any]:
    """컬렉션 문서 목록 (최신순). q 있으면 _id/주요 텍스트 필드 부분일치."""
    c = _coll(name)
    sort_key = COLLECTIONS[name]["sort"]
    flt: Dict[str, Any] = {}
    if q:
        flt = {"$or": [
            {"_id": {"$regex": q, "$options": "i"}},
            {"user_comment": {"$regex": q, "$options": "i"}},
            {"body": {"$regex": q, "$options": "i"}},
            {"summary": {"$regex": q, "$options": "i"}},
            {"text": {"$regex": q, "$options": "i"}},
            {"sender": {"$regex": q, "$options": "i"}},
        ]}
    total = c.count_documents(flt)
    cur = c.find(flt).sort(sort_key, -1).skip(skip).limit(min(limit, 200))
    return {"total": total, "skip": skip, "limit": limit,
            "docs": [_jsonable(d) for d in cur]}


def get_doc(name: str, doc_id: str) -> Optional[Dict[str, Any]]:
    d = _coll(name).find_one({"_id": doc_id})
    return _jsonable(d) if d else None


def delete_doc(name: str, doc_id: str) -> bool:
    return _coll(name).delete_one({"_id": doc_id}).deleted_count > 0


def rebrief_signals() -> Dict[str, Any]:
    """미요약 신호 강제 요약 (48h/7일 윈도우 무시)."""
    return signals_mod.rebrief_pending()


# ── 페르소나 편집 (베르·쿠키 말투/역할) ──────────────────────

# 어드민 표시 순서·라벨 (정체성 먼저, 역할 나중)
PERSONA_FIELDS = [
    ("berr_identity", "베르 — 정체성·말투"),
    ("berr_context", "베르 — 공통 맥락(산발 기록 등, 전 역할 공통)"),
    ("cookie_identity", "쿠키 — 정체성·말투"),
    ("insight_role", "베르 — 캡처 즉답 역할"),
    ("reason_role", "베르 — 사진 추론 역할"),
    ("chat_role", "베르 — 대화 역할"),
    ("quick_role", "쿠키 — 빠른 한마디 역할"),
    ("morning_role", "베르 — 조간 역할"),
    ("evening_role", "베르 — 석간 역할"),
]


def get_personas() -> Dict[str, Any]:
    """현재 적용 중인 페르소나 값 (override 또는 디폴트) + 라벨·디폴트 동시 제공."""
    from agent import personas
    return {
        "fields": [
            {"key": k, "label": label,
             "value": personas.current(k),
             "default": personas._DEFAULT[k],
             "overridden": personas.current(k) != personas._DEFAULT[k]}
            for k, label in PERSONA_FIELDS
        ]
    }


def set_persona(key: str, value: str) -> bool:
    """페르소나 한 필드 override 저장. value 비우면 디폴트로 복귀(필드 제거)."""
    from agent import personas
    if key not in personas.KEYS:
        raise ValueError(f"unknown persona key: {key}")
    if value and value.strip():
        db.settings().update_one(
            {"_id": "personas"}, {"$set": {key: value}}, upsert=True)
    else:
        db.settings().update_one({"_id": "personas"}, {"$unset": {key: ""}})


# ── 신호 요약 제외 패턴 (발신자·앱·본문에 부분일치하면 요약서 제외) ──
def get_signal_excludes() -> Dict[str, Any]:
    """어드민이 지정한 요약 제외 패턴 목록."""
    doc = db.settings().find_one({"_id": "signal_excludes"}) or {}
    return {"patterns": doc.get("patterns", [])}


def set_signal_excludes(patterns: List[str]) -> None:
    """제외 패턴 저장 (빈 줄 제거). 다음 요약부터 적용 — 원본 raw 신호는 그대로 남음."""
    clean = [str(p).strip() for p in (patterns or []) if str(p).strip()]
    db.settings().update_one(
        {"_id": "signal_excludes"}, {"$set": {"patterns": clean}}, upsert=True)


# ── 용도별 모델(LLM) 설정 ────────────────────────────────────
# (key, 라벨) — 어드민 노출 순서. 각 용도를 Nest 모델 중에서 직접 고른다.
TASK_ALIAS_FIELDS = [
    ("vision",       "사진 분석·코멘트 (베르)"),
    ("insight",      "텍스트·소리 즉답 (베르)"),
    ("quick",        "쿠키 — 텍스트·사진"),
    ("quick_av",     "쿠키 — 영상·음성"),
    ("audio",        "음성 인식"),
    ("chat",         "대화"),
    ("query",        "검색 Q&A"),
    ("signals",      "신호 분류 (⚠️ 로컬 모델만)"),
    ("daily_digest", "자정 일기·다이제스트"),
    ("embed",        "검색 임베딩"),
]


def get_task_aliases() -> Dict[str, Any]:
    """용도별 현재 모델 + 어드민 선택을 위한 Nest 모델 목록."""
    from config import TASK_ALIAS, task_alias
    doc = db.settings().find_one({"_id": "task_aliases"}) or {}
    try:
        import nest_client
        models = [m["alias"] for m in nest_client.list_models() if m.get("enabled")]
    except Exception:
        models = []
    return {
        "models": models,
        "fields": [
            {"key": k, "label": label,
             "value": doc.get(k, ""),            # 어드민 override (빈=env 디폴트)
             "effective": task_alias(k),          # 실제 적용 중인 값
             "default": TASK_ALIAS.get(k, "")}
            for k, label in TASK_ALIAS_FIELDS
        ],
    }


def set_task_alias(key: str, value: str) -> None:
    """용도(key)에 모델 지정. value 비우면 env 디폴트로 복귀(override 제거)."""
    if key not in {k for k, _ in TASK_ALIAS_FIELDS}:
        raise ValueError(f"unknown task: {key}")
    if value and value.strip():
        db.settings().update_one(
            {"_id": "task_aliases"}, {"$set": {key: value.strip()}}, upsert=True)
    else:
        db.settings().update_one({"_id": "task_aliases"}, {"$unset": {key: ""}})
    return True


# ── 동반자 말 걸기 설정 (텀·시간대·새벽 정지·위치 조건) ───────────
def get_companion_config() -> Dict[str, Any]:
    """현재 말 걸기 설정 + 마지막 발화 시각(분 전) + 이벤트 라벨."""
    import companion_config as cc
    return {
        "config": cc.get_config(),
        "state": cc.state_view(),
        "event_labels": cc.EVENT_LABELS,
    }


def set_companion_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """말 걸기 설정 저장(알려진 키만 정규화). 반환=병합된 설정."""
    import companion_config as cc
    return {"config": cc.set_config(patch or {})}
