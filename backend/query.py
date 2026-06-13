"""자연어 검색·질의 — 사용자의 자연어 질문 → LLM이 코퍼스(records + thread + 인덱스)에서 답.

구조:
1. master_index (vault) + 최근 candidate_records (Mongo) + silent_threads 수집
2. LLM에 prompt → 답변 + 참조 record_id (referenced)
3. Flutter는 referenced로 record 카드 thumbnail 표시 가능
"""

import json
import re
from typing import Dict, Any, List

from agent import llm
from agent import memory as memory_mod
import db
import index as index_mod
import threads as threads_mod
from config import task_alias


QUERY_SYSTEM = """당신은 유저의 일상 데이터에서 답을 찾는 비서입니다.

주어진 정보:
- master_index: 월별 통계·자주 등장한 태그·활성 thread (검색 진입점)
- candidate_records: 질문과 관련 있을 만한 항목들. 두 종류가 섞여 있음:
  - kind=record: 캡처 한 건 (ts, 유저 코멘트, VLM 묘사, LLM 인사이트, tags, thread_ids) — 구체적 사실
  - kind=journal: 그날 하루의 서술 일기 (date, text) — 거시 맥락·흐름
- silent_threads: 며칠째 무언급된 thread (질문이 펜딩 환기성이면 활용)

답변 원칙:
- 정확하고 친근한 한국어. 마크다운 가능.
- 근거가 된 캡처가 있으면 본문 끝에 다음 형식으로 참조 명시(record id만, 저널 id는 제외):
  `referenced: [rec-20260603-..., rec-20260602-...]`
- 데이터에 없으면 솔직히 "기록에 없어요" — 추측 X.
- 너무 길지 않게. 핵심 위주."""


def _record_candidate(r: Dict[str, Any]) -> Dict[str, Any]:
    ts = r.get("ts")
    c = {
        "id": r["_id"],
        "kind": "record",
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
        "user_comment": (r.get("user_comment") or "")[:250],
        "vlm": ((r.get("vlm") or {}).get("caption") or "")[:250],
        "insight": ((r.get("insight") or {}).get("text") or "")[:250],
        "tags": (r.get("tags") or [])[:5],
        "thread_ids": r.get("thread_ids") or [],
        "type": r.get("type_hint"),
    }
    # 음성 캡처는 audio.caption에만 내용이 있음 — 빼면 검색에서 안 보임
    audio_cap = ((r.get("audio") or {}).get("caption") or "")[:250]
    if audio_cap:
        c["audio"] = audio_cap
    return c


def _journal_candidate(j: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": j["_id"],
        "kind": "journal",
        "date": j.get("date"),
        "text": (j.get("text") or "")[:1200],
    }


def build_candidates(question: str, limit: int = 30) -> List[Dict[str, Any]]:
    """질문 관련 후보(record+journal) 수집 — query/chat 공용.

    agent.memory 3요소 스코어(유사도+최근성+중요도)로 저널+record 합집합 top-k.
    임베딩 불가(alias 미설정/Nest 실패/임베딩된 후보 없음) 시 최근순 fallback — graceful.
    """
    hits = memory_mod.search(question, top_k=limit)
    candidates: List[Dict[str, Any]] = []
    if hits:
        rec_ids = [h["id"] for h in hits if h.get("kind") == "record"]
        jrn_ids = [h["id"] for h in hits if h.get("kind") == "journal"]
        rec_by_id = {r["_id"]: r for r in db.records().find({"_id": {"$in": rec_ids}})}
        jrn_by_id = {j["_id"]: j for j in db.journals().find({"_id": {"$in": jrn_ids}})}
        for h in hits:   # 스코어 순서 유지
            if h.get("kind") == "record" and h["id"] in rec_by_id:
                candidates.append(_record_candidate(rec_by_id[h["id"]]))
            elif h.get("kind") == "journal" and h["id"] in jrn_by_id:
                candidates.append(_journal_candidate(jrn_by_id[h["id"]]))
    else:
        # fallback: 최근 record + 최근 일 저널
        for r in db.records().find().sort("ts", -1).limit(limit):
            candidates.append(_record_candidate(r))
        for j in db.journals().find({"kind": "day"}).sort("period_start", -1).limit(7):
            candidates.append(_journal_candidate(j))
    return candidates


def extract_referenced(text: str) -> tuple:
    """LLM 답변 끝의 `referenced: [rec-...]` 추출 → (본문, record_id 리스트).

    query/chat 공용 — 본문에서 referenced 줄은 제거(중복 표시 방지).
    """
    referenced: List[str] = []
    m = re.search(r"referenced\s*[:：]\s*\[([^\]]*)\]", text)
    if m:
        referenced = re.findall(r"rec-[\w-]+", m.group(1))
        text = re.sub(r"\n*`?referenced\s*[:：][^\n]*", "", text).strip()
    return text, referenced


def query(question: str, limit: int = 30) -> Dict[str, Any]:
    """자연어 질문 처리. 동기 호출, FastAPI threadpool에서 실행됨.

    Returns: {"answer": str, "referenced": [record_id...], "alias": str}.
    """
    alias = task_alias("query") or llm.default_alias()
    if not alias:
        return {
            "answer": "(query alias 미설정 — Nest에 enabled 모델 없음)",
            "referenced": [],
        }

    master = index_mod.read_master_index() or "(인덱스 아직 생성 안 됨)"
    candidates = build_candidates(question, limit)
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
        r = llm.call(alias, prompt, system=QUERY_SYSTEM)
        text = (r.get("text") or "").strip()
    except Exception as e:
        return {"answer": f"(질의 실패: {e})", "referenced": []}

    text, referenced = extract_referenced(text)
    return {
        "answer": text,
        "referenced": referenced,
        "alias": alias,
    }
