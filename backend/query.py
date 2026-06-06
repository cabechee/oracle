"""자연어 검색·질의 — 사용자의 자연어 질문 → LLM이 코퍼스(records + thread + 인덱스)에서 답.

구조:
1. master_index (vault) + 최근 candidate_records (Mongo) + silent_threads 수집
2. LLM에 prompt → 답변 + 참조 record_id (referenced)
3. Flutter는 referenced로 record 카드 thumbnail 표시 가능
"""

import json
import re
from typing import Dict, Any, List

import nest_client
import embedding as embedding_mod
import db
import digest as digest_mod
import threads as threads_mod
from config import TASK_ALIAS


QUERY_SYSTEM = """당신은 유저의 일상 데이터에서 답을 찾는 비서입니다.

주어진 정보:
- master_index: 월별 통계·자주 등장한 태그·활성 thread (검색 진입점)
- candidate_records: 질문과 관련 있을 만한 record들 (시각: ts, 유저 코멘트, VLM 묘사, LLM 인사이트, tags, thread_ids)
- silent_threads: 며칠째 무언급된 thread (질문이 펜딩 환기성이면 활용)

답변 원칙:
- 정확하고 친근한 한국어. 마크다운 가능.
- 근거가 있으면 본문 끝에 다음 형식으로 참조 명시:
  `referenced: [rec-20260603-..., rec-20260602-...]`
- 데이터에 없으면 솔직히 "기록에 없어요" — 추측 X.
- 너무 길지 않게. 핵심 위주."""


def query(question: str, limit: int = 30) -> Dict[str, Any]:
    """자연어 질문 처리. 동기 호출, FastAPI threadpool에서 실행됨.

    Returns: {"answer": str, "referenced": [record_id...], "alias": str}.
    """
    alias = TASK_ALIAS.get("query") or nest_client.default_alias()
    if not alias:
        return {
            "answer": "(query alias 미설정 — Nest에 enabled 모델 없음)",
            "referenced": [],
        }

    master = digest_mod.read_master_index() or "(인덱스 아직 생성 안 됨)"

    # 후보 records — 임베딩 의미검색 top-k. 임베딩 불가(alias 미설정/Nest 실패/
    # 임베딩된 record 없음) 시 최근순 fallback — graceful.
    hits = embedding_mod.search(question, top_k=limit)
    if hits:
        ids = [h[0] for h in hits]
        by_id = {r["_id"]: r for r in db.records().find({"_id": {"$in": ids}})}
        rows = [by_id[i] for i in ids if i in by_id]   # 유사도 순서 유지
    else:
        rows = list(db.records().find().sort("ts", -1).limit(limit))

    candidates: List[Dict[str, Any]] = []
    for r in rows:
        ts = r.get("ts")
        candidates.append({
            "id": r["_id"],
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
            "user_comment": (r.get("user_comment") or "")[:250],
            "vlm": ((r.get("vlm") or {}).get("caption") or "")[:250],
            "insight": ((r.get("insight") or {}).get("text") or "")[:250],
            "tags": (r.get("tags") or [])[:5],
            "thread_ids": r.get("thread_ids") or [],
            "type": r.get("type_hint"),
        })

    silent = threads_mod.silent_threads(min_days=3, max_days=30)

    prompt = (
        f"## 질문\n{question}\n\n"
        f"## master_index\n{master[:1500]}\n\n"
        f"## candidate_records ({len(candidates)}건)\n"
        f"{json.dumps(candidates, ensure_ascii=False)}\n\n"
        f"## silent_threads\n"
        f"{json.dumps(silent, ensure_ascii=False)}\n\n"
        f"위 정보를 보고 질문에 답하세요. 근거가 된 record가 있으면 본문 끝에 "
        f"`referenced: [record_id1, record_id2, ...]` 형식으로 명시."
    )

    try:
        r = nest_client.call(alias=alias, prompt=prompt, system=QUERY_SYSTEM)
        text = (r.get("text") or "").strip()
    except Exception as e:
        return {"answer": f"(질의 실패: {e})", "referenced": []}

    # referenced parse — 'rec-' 패턴 추출
    referenced: List[str] = []
    m = re.search(r"referenced\s*[:：]\s*\[([^\]]*)\]", text)
    if m:
        referenced = re.findall(r"rec-[\w-]+", m.group(1))
        # 본문에서 referenced 줄 제거(중복 표시 방지)
        text = re.sub(r"\n*referenced\s*[:：][^\n]*", "", text).strip()

    return {
        "answer": text,
        "referenced": referenced,
        "alias": alias,
    }
