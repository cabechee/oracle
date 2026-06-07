"""캡처 인입 파이프라인 — Layer 1 핵심.

사진/텍스트/음성 인입 → VLM 캡션 + LLM 즉답 → Record(MongoDB) + vault append.
type/태그/thread는 자정 배치가 부착 (여기선 null/빈리스트로 둠).

원칙:
- VLM·LLM 응답까지 *전부 다* 평문화해서 vault에 append (사용자 결정 2026-06-02).
- 즉답 인사이트는 모든 캡처에 트리거 (사용자 결정).
- 구조화는 자정에 — ingest는 가능한 한 단순·빠르게.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import nest_client
import corpus
import db
from config import TASK_ALIAS, CONTEXT_MINUTES, CONTEXT_MAX


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


def _recent_context(now: datetime) -> str:
    """최근 캡처(시간 윈도우 + 개수 상한)를 insight 맥락 문자열로. 없으면 빈 문자열.

    메시지 사이 연속성용 — 직전 캡처들의 유저 코멘트·인사이트를 시간순으로.
    """
    if CONTEXT_MAX <= 0:
        return ""
    since = now - timedelta(minutes=CONTEXT_MINUTES)
    try:
        rows = list(
            db.records()
            .find({"ts": {"$gte": since, "$lt": now}},
                  {"user_comment": 1, "insight": 1, "ts": 1})
            .sort("ts", -1)
            .limit(CONTEXT_MAX)
        )
    except Exception:
        return ""
    rows.reverse()  # 오래된 → 최근 순
    lines: List[str] = []
    for r in rows:
        ts = r.get("ts")
        t = ts.strftime("%H:%M") if hasattr(ts, "strftime") else ""
        c = (r.get("user_comment") or "").strip()
        ins = ((r.get("insight") or {}).get("text") or "").strip()
        parts = []
        if c:
            parts.append(f"유저: {c}")
        if ins:
            parts.append(f"나: {ins[:120]}")
        if parts:
            lines.append(f"[{t}] " + " / ".join(parts))
    return "\n".join(lines)


def _summarize_analysis(analysis) -> str:
    """사진 분석 JSON → 사람/검색용 한 줄 요약 (vlm.caption 호환)."""
    if not analysis:
        return ""
    parts = []
    scene = str(analysis.get("scene") or "").strip()
    if scene:
        parts.append(scene)
    objs = analysis.get("objects") or []
    if objs:
        parts.append("객체: " + ", ".join(str(o) for o in objs[:8]))
    ocr = str(analysis.get("ocr_text") or "").strip()
    if ocr:
        parts.append("글자: " + ocr[:150])
    return " · ".join(parts)


VLM_SYSTEM = """당신은 사진을 풍부하게 묘사하는 보조입니다.
- 객체, 텍스트(OCR로 읽히는 글자 전부), 색감, 분위기, 맥락을 평문 한 단락으로.
- 사실 묘사만. 의견·해석·추천은 다음 단계 LLM의 몫.
- 한국어 2~5문장."""


INSIGHT_SYSTEM = """당신은 유저의 일상을 함께 보는 채팅 동반자이자 비서입니다.
- 유저가 던진 사진·코멘트에서 흥미로운 인사이트·관점·맥락 연결을 한 단락 만듭니다.
- "이건 사과네요" 같은 평범한 사실 설명은 절대 X. 발견·놀라움·연결·실용 조언이 있어야 합니다.
- 사진이 있으면 시각적 디테일을 짚고, 코멘트만 있으면 그 의도를 살려 응답하세요.
- 최신정보(웹)는 정말 도움될 때만 사용.
- 한국어로 자연스럽게 2~5문장. 친근하고 간결한 말투. 답을 굳이 정형화하지 마세요.
- [최근 맥락]이 주어지면 직전 흐름을 자연스럽게 이어가되, 같은 말 반복하지 말고 연결·발전시키세요."""


AUDIO_SYSTEM = """당신은 오디오에서 소리를 인식하는 보조입니다.
- 들리는 소리를 종류별로 묘사하세요(말소리·음악·환경음·기계음 등).
- 사람 말이 있으면 들리는 그대로 한국어로 전사하고, 화자 구분이 가능하면 표시.
- 음악이면 분위기·장르·악기를, 환경음이면 장소·상황을 추정.
- 사실 묘사 위주. 의견·해석은 다음 단계 LLM의 몫. 한국어 2~5문장."""


def ingest(
    user_comment: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_ext: str = "jpg",
    model: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    audio_ext: str = "m4a",
    video_bytes: Optional[bytes] = None,
    video_ext: str = "mp4",
) -> Dict[str, Any]:
    """캡처 한 건 인입 — Record 생성 + 즉답 반환.

    model: Nest alias(예: 'claude', 'codex', 'gemini', 'qwen-vlm', 'trio').
           None이면 TASK_ALIAS 디폴트 사용. 사용자가 폰 UI에서 선택한 값이 들어옴.
    audio_bytes: 녹음 오디오(있으면 저장 + 소리 인식). audio alias 미설정이면 저장만.

    Returns: {record_id, ts, insight, vlm_caption, audio_caption, vault_path, image_paths, audio_paths}.
    """
    if not user_comment and not image_bytes and not audio_bytes and not video_bytes:
        raise ValueError("comment·image·audio·video 중 하나 이상 필요")

    ts = datetime.now()
    record_id = f"rec-{ts.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # 1. 이미지 저장 (vault 옆에) — 있으면. 절대경로(nest 호출용) + 상대경로(저장/응답용) 둘 다 유지.
    abs_paths: List[str] = []
    if image_bytes:
        abs_paths.append(corpus.save_image(ts, 1, image_bytes, image_ext))
    image_paths: List[str] = [corpus.to_vault_rel(p) for p in abs_paths]

    # 오디오 저장 (있으면) — 절대경로(nest 호출용) + 상대경로(저장/응답용)
    audio_abs: List[str] = []
    if audio_bytes:
        audio_abs.append(corpus.save_audio(ts, 1, audio_bytes, audio_ext))
    audio_paths: List[str] = [corpus.to_vault_rel(p) for p in audio_abs]

    # 영상 저장 (있으면) — 현재는 저장만, 인식은 보류(멀티모달 API 붙이면 활성화)
    video_abs: List[str] = []
    if video_bytes:
        video_abs.append(corpus.save_video(ts, 1, video_bytes, video_ext))
    video_paths: List[str] = [corpus.to_vault_rel(p) for p in video_abs]

    # EXIF GPS — 사진 첫 장에서 추출, prompt + record에 location 힌트로
    location: Optional[str] = None
    if abs_paths:
        location = _exif_location(abs_paths[0])
    location_hint = f"\n[사진 GPS: {location}]" if location else ""

    # 사진 첨부 → Nest용 이미지 (사진 3단계 vision에서 사용)
    nest_images = nest_client.images_from_paths(abs_paths) if abs_paths else None

    # 2.5 소리 인식 — 명시된 오디오 모델(TASK_ALIAS['audio'])이 있을 때만.
    # 아무 모델(claude 등)에 오디오를 보내면 안 되므로 default/폰 model 폴백을 쓰지 않는다.
    # 현재 Nest에 오디오 인식 모델이 없으면 ORACLE_AUDIO 를 비워둠 → 저장만.
    audio_caption = ""
    audio_alias: Optional[str] = TASK_ALIAS.get("audio") or None
    if audio_abs and audio_alias:
        try:
            r = nest_client.call(
                alias=audio_alias,
                prompt=("이 오디오에서 들리는 소리를 묘사하고, 말이 있으면 그대로 전사해주세요."
                        + location_hint),
                audio=nest_client.audio_from_paths(audio_abs),
                system=AUDIO_SYSTEM,
            )
            audio_caption = (r.get("text") or "").strip()
        except Exception as e:
            audio_caption = f"(소리 인식 실패: {e})"
    # audio_alias 없으면 저장만 (audio_caption 빈 문자열)

    # 2~3. 인사이트 — 사진이면 3단계(분석→코멘트→제안), 아니면 텍스트/오디오 단일.
    context_block = _recent_context(ts)
    insight_alias = _resolve_alias("insight", model, prefer_vision=bool(abs_paths))
    vlm_alias: Optional[str] = None
    vlm_caption = ""
    analysis: Optional[Dict[str, Any]] = None
    suggestion = ""
    insight_text = ""

    if not insight_alias:
        insight_text = "(insight alias 미설정 — Nest에 enabled 모델 없음)"
        insight_alias = ""

    # 이번 입력(코멘트 + 소리 + GPS) 한 덩어리
    _ui: List[str] = []
    if user_comment:
        _ui.append(f"코멘트: {user_comment}")
    if audio_caption:
        _ui.append(f"소리: {audio_caption}")
    user_input = " / ".join(_ui) + location_hint

    if abs_paths and insight_alias:
        # 사진 3단계 (describe-then-reason): 분석 JSON → 맥락 코멘트 + 디스커버리 제안
        from agent import vision
        try:
            v = vision.process(insight_alias, nest_images,
                               user_input=user_input, context=context_block, memory="")
            analysis = v["analysis"]
            insight_text = v["comment"] or "(코멘트 생성 실패)"
            suggestion = v["suggestion"]
            vlm_alias = insight_alias
            vlm_caption = _summarize_analysis(analysis)
        except Exception as e:
            insight_text = f"(인사이트 생성 실패: {e})"
    elif insight_alias:
        # 텍스트/오디오만 — 단일 인사이트
        prompt_parts: List[str] = []
        if user_comment:
            prompt_parts.append(f"[유저 코멘트]\n{user_comment}")
        if audio_caption:
            prompt_parts.append(f"[소리]\n{audio_caption}")
        insight_prompt = ("\n\n".join(prompt_parts) or "(빈 입력)") + location_hint
        if context_block:
            insight_prompt = (
                f"[최근 맥락 — 직전 대화 흐름, 참고만]\n{context_block}\n\n"
                f"---\n\n[지금 입력]\n{insight_prompt}"
            )
        try:
            r = nest_client.call(alias=insight_alias, prompt=insight_prompt,
                                 system=INSIGHT_SYSTEM)
            insight_text = (r.get("text") or "").strip()
        except Exception as e:
            insight_text = f"(인사이트 생성 실패: {e})"

    # 4. Vault 평문 append (정본) — LLM 응답까지 전부 평문화
    #    (vault 마크다운 안에선 절대→상대 변환됨 — append_record가 처리)
    anchor = corpus.append_record(
        ts=ts,
        record_id=record_id,
        user_comment=user_comment or "",
        image_paths=abs_paths,
        vlm_caption=vlm_caption,
        insight_text=insight_text,
        suggestion=suggestion,
        audio_paths=audio_abs,
        audio_caption=audio_caption,
        video_paths=video_abs,
    )
    vault_rel = corpus.day_vault_path(ts)
    vault_path = f"{vault_rel}#{anchor}"

    # 5. MongoDB Record (메타/인덱스용)
    rec: Dict[str, Any] = {
        "_id": record_id,
        "ts": ts,
        "vault_path": vault_path,
        "image_paths": image_paths,
        "audio_paths": audio_paths,
        "video_paths": video_paths,
        "user_comment": user_comment or "",
        "location": location,    # "lat,lon" 문자열 또는 None
        "vlm": {"alias": vlm_alias, "caption": vlm_caption} if vlm_alias else None,
        "analysis": analysis,                              # 사진 3단계 1단계 JSON (신규)
        "audio": {"alias": audio_alias, "caption": audio_caption} if audio_alias else None,
        "insight": {"alias": insight_alias, "text": insight_text},
        "suggestion": suggestion or None,                  # 디스커버리 제안 (신규)
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
        "suggestion": suggestion,
        "analysis": analysis,
        "vlm_caption": vlm_caption,
        "audio_caption": audio_caption,
        "vault_path": vault_path,
        "image_paths": image_paths,   # vault-relative
        "audio_paths": audio_paths,
        "video_paths": video_paths,
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
    """응답 정규화: ts → ISO 문자열, image/audio_paths → vault-relative, 내부 임베딩 제거."""
    if hasattr(r.get("ts"), "isoformat"):
        r["ts"] = r["ts"].isoformat()
    r["image_paths"] = [corpus.to_vault_rel(p) for p in r.get("image_paths", []) or []]
    r["audio_paths"] = [corpus.to_vault_rel(p) for p in r.get("audio_paths", []) or []]
    r["video_paths"] = [corpus.to_vault_rel(p) for p in r.get("video_paths", []) or []]
    r.pop("embedding", None)   # 내부 검색용 벡터 — 폰에 안 보냄
    r.pop("embed_meta", None)
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
