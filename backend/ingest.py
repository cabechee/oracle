"""캡처 인입 파이프라인 — Layer 1 핵심.

사진/텍스트/음성 인입 → VLM 캡션 + LLM 즉답 → Record(MongoDB) + vault append.
type/태그/thread는 자정 배치가 부착 (여기선 null/빈리스트로 둠).

원칙:
- VLM·LLM 응답까지 *전부 다* 평문화해서 vault에 append (사용자 결정 2026-06-02).
- 즉답 인사이트는 모든 캡처에 트리거 (사용자 결정).
- 구조화는 자정에 — ingest는 가능한 한 단순·빠르게.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

import nest_client
import corpus
import db
from config import TASK_ALIAS


VLM_SYSTEM = """당신은 사진을 풍부하게 묘사하는 보조입니다.
- 객체, 텍스트(OCR로 읽히는 글자 전부), 색감, 분위기, 맥락을 평문 한 단락으로.
- 사실 묘사만. 의견·해석·추천은 다음 단계 LLM의 몫.
- 한국어 2~5문장."""


INSIGHT_SYSTEM = """당신은 유저의 일상을 함께 보는 채팅 동반자이자 비서입니다.
- 유저가 던진 사진·코멘트에서 흥미로운 인사이트·관점·맥락 연결을 한 단락 만듭니다.
- "이건 사과네요" 같은 평범한 사실 설명은 절대 X. 발견·놀라움·연결·실용 조언이 있어야 합니다.
- 사진이 있으면 시각적 디테일을 짚고, 코멘트만 있으면 그 의도를 살려 응답하세요.
- 최신정보(웹)는 정말 도움될 때만 사용.
- 한국어로 자연스럽게 2~5문장. 친근하고 간결한 말투. 답을 굳이 정형화하지 마세요."""


def ingest(
    user_comment: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_ext: str = "jpg",
) -> Dict[str, Any]:
    """캡처 한 건 인입 — Record 생성 + 즉답 반환.

    Returns: {record_id, ts, insight, vlm_caption, vault_path, image_paths}.
    """
    if not user_comment and not image_bytes:
        raise ValueError("comment 또는 image 중 하나 이상 필요")

    ts = datetime.now()
    record_id = f"rec-{ts.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # 1. 이미지 저장 (vault 옆에) — 있으면
    image_paths: List[str] = []
    if image_bytes:
        path = corpus.save_image(ts, 1, image_bytes, image_ext)
        image_paths.append(path)

    # 2. VLM 캡션 — 이미지가 있을 때만
    vlm_caption = ""
    vlm_alias: Optional[str] = None
    nest_images = nest_client.images_from_paths(image_paths) if image_paths else None
    if image_paths:
        vlm_alias = TASK_ALIAS["vlm_caption"]
        try:
            r = nest_client.call(
                alias=vlm_alias,
                prompt="이 사진을 풍부하게 묘사해주세요. 보이는 모든 객체·글자·맥락을 한 단락으로.",
                images=nest_images,
                system=VLM_SYSTEM,
            )
            vlm_caption = (r.get("text") or "").strip()
        except Exception as e:
            vlm_caption = f"(VLM 실패: {e})"

    # 3. LLM 즉답 인사이트 — 항상 (사용자 결정: 전부 트리거)
    insight_alias = TASK_ALIAS["insight"]
    prompt_parts: List[str] = []
    if user_comment:
        prompt_parts.append(f"[유저 코멘트]\n{user_comment}")
    if vlm_caption:
        prompt_parts.append(f"[사진 묘사]\n{vlm_caption}")
    insight_prompt = "\n\n".join(prompt_parts) or "(빈 입력)"

    try:
        r = nest_client.call(
            alias=insight_alias,
            prompt=insight_prompt,
            images=nest_images,
            system=INSIGHT_SYSTEM,
        )
        insight_text = (r.get("text") or "").strip()
    except Exception as e:
        insight_text = f"(인사이트 생성 실패: {e})"

    # 4. Vault 평문 append (정본) — LLM 응답까지 전부 평문화
    anchor = corpus.append_record(
        ts=ts,
        record_id=record_id,
        user_comment=user_comment or "",
        image_paths=image_paths,
        vlm_caption=vlm_caption,
        insight_text=insight_text,
    )
    vault_rel = corpus.day_vault_path(ts)
    vault_path = f"{vault_rel}#{anchor}"

    # 5. MongoDB Record (메타/인덱스용)
    rec: Dict[str, Any] = {
        "_id": record_id,
        "ts": ts,
        "vault_path": vault_path,
        "image_paths": image_paths,
        "user_comment": user_comment or "",
        "vlm": {"alias": vlm_alias, "caption": vlm_caption} if vlm_alias else None,
        "insight": {"alias": insight_alias, "text": insight_text},
        "reaction": None,
        # 자정 배치가 부착할 것들 — 시작은 null/빈리스트
        "type_hint": None,
        "tags": [],
        "thread_ids": [],
    }
    db.records().insert_one(rec)

    return {
        "record_id": record_id,
        "ts": ts.isoformat(),
        "insight": insight_text,
        "vlm_caption": vlm_caption,
        "vault_path": vault_path,
        "image_paths": image_paths,
    }


def set_reaction(record_id: str, reaction: str) -> bool:
    """유저 이모지 피드백 (interesting | useful | skip 등 자유)."""
    res = db.records().update_one(
        {"_id": record_id},
        {"$set": {"reaction": reaction}},
    )
    return res.matched_count > 0


def list_recent(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """최근 Record N개 (채팅 무한 스크롤용)."""
    cur = (
        db.records()
        .find()
        .sort("ts", -1)
        .skip(offset)
        .limit(limit)
    )
    out: List[Dict[str, Any]] = []
    for r in cur:
        if hasattr(r.get("ts"), "isoformat"):
            r["ts"] = r["ts"].isoformat()
        out.append(r)
    return out


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    r = db.records().find_one({"_id": record_id})
    if r and hasattr(r.get("ts"), "isoformat"):
        r["ts"] = r["ts"].isoformat()
    return r
