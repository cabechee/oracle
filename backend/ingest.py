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


def _exif_location(path: str) -> Optional[str]:
    """이미지 EXIF에서 GPS 좌표(위도,경도) 문자열 추출. 없거나 실패하면 None.

    카메라 직촬 사진에는 GPS EXIF가 있고, 갤러리에서 받은 사진도 원본 EXIF가 있으면 추출 가능.
    image_picker로 resize된 경우 EXIF가 lose됐을 수 있음 — graceful.
    """
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
        with Image.open(path) as img:
            exif = img._getexif() or {}
        gps_info: Dict[Any, Any] = {}
        for tag_id, value in exif.items():
            if TAGS.get(tag_id) == "GPSInfo" and isinstance(value, dict):
                gps_info = {GPSTAGS.get(k, k): v for k, v in value.items()}
                break
        if not gps_info:
            return None
        lat_v = gps_info.get("GPSLatitude")
        lat_r = gps_info.get("GPSLatitudeRef")
        lon_v = gps_info.get("GPSLongitude")
        lon_r = gps_info.get("GPSLongitudeRef")
        if not (lat_v and lat_r and lon_v and lon_r):
            return None

        def _deg(triplet, ref) -> float:
            d, m, s = (float(triplet[0]), float(triplet[1]), float(triplet[2]))
            r = d + m / 60 + s / 3600
            return -r if ref in ("S", "W") else r

        lat = _deg(lat_v, lat_r)
        lon = _deg(lon_v, lon_r)
        return f"{lat:.6f},{lon:.6f}"
    except Exception:
        return None


def _resolve_alias(task_key: str, override: Optional[str], prefer_vision: bool) -> Optional[str]:
    """alias 결정 chain — Nest 변경에 동적 반응.

    1. 사용자 명시 선택(폰 UI) → 그대로
    2. env TASK_ALIAS 설정 → 그대로
    3. 둘 다 비어있음 → Nest에 등록된 enabled 모델 중 첫 모델 자동 선택
    """
    if override:
        return override
    env_alias = TASK_ALIAS.get(task_key) or ""
    if env_alias:
        return env_alias
    return nest_client.default_alias(prefer_vision=prefer_vision)


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
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """캡처 한 건 인입 — Record 생성 + 즉답 반환.

    model: Nest alias(예: 'claude', 'codex', 'gemini', 'qwen-vlm', 'trio').
           None이면 TASK_ALIAS 디폴트 사용. 사용자가 폰 UI에서 선택한 값이 들어옴.

    Returns: {record_id, ts, insight, vlm_caption, vault_path, image_paths}.
    """
    if not user_comment and not image_bytes:
        raise ValueError("comment 또는 image 중 하나 이상 필요")

    ts = datetime.now()
    record_id = f"rec-{ts.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # 1. 이미지 저장 (vault 옆에) — 있으면. 절대경로(nest 호출용) + 상대경로(저장/응답용) 둘 다 유지.
    abs_paths: List[str] = []
    if image_bytes:
        abs_paths.append(corpus.save_image(ts, 1, image_bytes, image_ext))
    image_paths: List[str] = [corpus.to_vault_rel(p) for p in abs_paths]

    # EXIF GPS — 사진 첫 장에서 추출, prompt + record에 location 힌트로
    location: Optional[str] = None
    if abs_paths:
        location = _exif_location(abs_paths[0])
    location_hint = f"\n[사진 GPS: {location}]" if location else ""

    # 2. VLM 캡션 — 이미지가 있을 때만. alias는 동적 chain으로 결정.
    vlm_caption = ""
    vlm_alias: Optional[str] = None
    nest_images = nest_client.images_from_paths(abs_paths) if abs_paths else None
    if abs_paths:
        vlm_alias = _resolve_alias("vlm_caption", model, prefer_vision=True)
        if vlm_alias:
            try:
                r = nest_client.call(
                    alias=vlm_alias,
                    prompt=(
                        "이 사진을 풍부하게 묘사해주세요. 보이는 모든 객체·글자·맥락을 한 단락으로."
                        + location_hint
                    ),
                    images=nest_images,
                    system=VLM_SYSTEM,
                )
                vlm_caption = (r.get("text") or "").strip()
            except Exception as e:
                vlm_caption = f"(VLM 실패: {e})"
        else:
            vlm_caption = "(VLM alias 미설정 — Nest에 enabled 모델 없음)"

    # 3. LLM 즉답 인사이트 — 항상 (사용자 결정: 전부 트리거). 동적 chain.
    insight_alias = _resolve_alias("insight", model, prefer_vision=bool(abs_paths))
    if not insight_alias:
        insight_text = "(insight alias 미설정 — Nest에 enabled 모델 없음)"
        # 빈 alias로 nest_client.call 호출 방지
        insight_alias = ""
    prompt_parts: List[str] = []
    if user_comment:
        prompt_parts.append(f"[유저 코멘트]\n{user_comment}")
    if vlm_caption:
        prompt_parts.append(f"[사진 묘사]\n{vlm_caption}")
    insight_prompt = ("\n\n".join(prompt_parts) or "(빈 입력)") + location_hint

    if insight_alias:
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
    # 위 _resolve_alias 실패 시 insight_text는 이미 설정됨

    # 4. Vault 평문 append (정본) — LLM 응답까지 전부 평문화
    #    (vault 마크다운 안에선 절대→상대 변환됨 — append_record가 처리)
    anchor = corpus.append_record(
        ts=ts,
        record_id=record_id,
        user_comment=user_comment or "",
        image_paths=abs_paths,
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
        "location": location,    # "lat,lon" 문자열 또는 None
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
        "image_paths": image_paths,   # vault-relative
    }


def update_comment(record_id: str, new_comment: str) -> bool:
    """잘못 보낸 record의 user_comment 수정. vault 평문은 append-only 원칙대로 그대로 두고
    MongoDB(UI source)만 갱신."""
    res = db.records().update_one(
        {"_id": record_id},
        {"$set": {"user_comment": new_comment}},
    )
    return res.matched_count > 0


def set_reaction(record_id: str, reaction: str) -> bool:
    """유저 이모지 피드백 (interesting | useful | skip 등 자유)."""
    res = db.records().update_one(
        {"_id": record_id},
        {"$set": {"reaction": reaction}},
    )
    return res.matched_count > 0


def _normalize(r: Dict[str, Any]) -> Dict[str, Any]:
    """응답 정규화: ts → ISO 문자열, image_paths → vault-relative (legacy 절대경로도 변환)."""
    if hasattr(r.get("ts"), "isoformat"):
        r["ts"] = r["ts"].isoformat()
    r["image_paths"] = [corpus.to_vault_rel(p) for p in r.get("image_paths", []) or []]
    return r


def list_recent(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """최근 Record N개 (채팅 무한 스크롤용)."""
    cur = (
        db.records()
        .find()
        .sort("ts", -1)
        .skip(offset)
        .limit(limit)
    )
    return [_normalize(r) for r in cur]


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    r = db.records().find_one({"_id": record_id})
    return _normalize(r) if r else None
