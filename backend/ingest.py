"""캡처 인입 파이프라인 — Layer 1 핵심.

사진/텍스트/음성 인입 → VLM 캡션 + LLM 즉답 → Record(MongoDB) + vault append.
type/태그/thread는 자정 배치가 부착 (여기선 null/빈리스트로 둠).

동기/비동기 두 경로:
- ingest(): 동기 — LLM까지 끝내고 완성 record 반환 (구버전 앱 호환).
- ingest_async_start() / ingest_async_finish(): 비동기 — 미디어 저장 + stub record
  (status="processing")를 즉시 반환, LLM·vault append는 백그라운드에서 완료
  (status="done"|"failed"). 앱은 record_id 폴링으로 완료 감지.
  (사진 3단계 실측 150s+ 동안 HTTP 연결을 잡아두지 않기 위함.)

원칙:
- VLM·LLM 응답까지 *전부 다* 평문화해서 vault에 append (사용자 결정 2026-06-02).
  비동기 경로에서도 vault append는 완료 시점 1회 — 정본에 미완성 기록을 남기지 않는다.
- 즉답 인사이트는 모든 캡처에 트리거 (사용자 결정).
- 구조화는 자정에 — ingest는 가능한 한 단순·빠르게.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

import nest_client
import corpus
import db
import embedding as embedding_mod
from agent import llm
from agent import memory as memory_mod
from config import task_alias


def _gps_to_str(gps_info: Dict[Any, Any]) -> Optional[str]:
    """GPSInfo dict → "위도,경도" 문자열. 불완전하면 None."""
    try:
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

        return f"{_deg(lat_v, lat_r):.6f},{_deg(lon_v, lon_r):.6f}"
    except Exception:
        return None


def _exif_meta(src: Any) -> Dict[str, Any]:
    """이미지 EXIF에서 촬영시각·GPS·기기·방향을 최대한 추출. 없으면 빈 dict (graceful).

    src = 파일경로(str) 또는 이미지 bytes. 백필은 저장 전 bytes에서 촬영시각을 읽어
    캡처 ts를 정해야 하므로 bytes 입력을 지원한다.
    카메라 직촬은 EXIF가 풍부하고 갤러리/공유 사진도 원본 EXIF가 남아있으면 추출 가능.
    image_picker resize로 EXIF가 손실됐을 수 있음 — 그땐 빈 dict.
    """
    meta: Dict[str, Any] = {}
    try:
        import io
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
        img_src = io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src
        with Image.open(img_src) as img:
            exif = img._getexif() or {}
        if not exif:
            return meta
        tags: Dict[Any, Any] = {}
        gps_info: Dict[Any, Any] = {}
        for tag_id, value in exif.items():
            name = TAGS.get(tag_id, tag_id)
            if name == "GPSInfo" and isinstance(value, dict):
                gps_info = {GPSTAGS.get(k, k): v for k, v in value.items()}
            else:
                tags[name] = value
        # 촬영 시각 — 원본 우선 ("YYYY:MM:DD HH:MM:SS")
        dt = (tags.get("DateTimeOriginal") or tags.get("DateTimeDigitized")
              or tags.get("DateTime"))
        if dt:
            meta["datetime"] = str(dt).strip()
        # 기기
        device = (str(tags.get("Make") or "").strip() + " "
                  + str(tags.get("Model") or "").strip()).strip()
        if device:
            meta["device"] = device
        # 방향(Orientation) — 1=정상, 3/6/8=회전
        ori = tags.get("Orientation")
        if ori:
            meta["orientation"] = int(ori) if str(ori).isdigit() else ori
        # GPS
        loc = _gps_to_str(gps_info)
        if loc:
            meta["gps"] = loc
    except Exception:
        pass
    return meta


def _exif_dt_to_datetime(s: str) -> Optional[datetime]:
    """EXIF datetime 문자열("YYYY:MM:DD HH:MM:SS") → datetime. 실패 None."""
    try:
        return datetime.strptime(s.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def _resolve_alias(task_key: str, override: Optional[str], prefer_vision: bool,
                   fallback_key: Optional[str] = None) -> Optional[str]:
    """alias 결정 chain — Nest 변경에 동적 반응.

    1. 사용자 명시 선택(폰 UI) → 그대로
    2. 어드민/env task_alias 설정 → 그대로
    3. fallback_key 있으면 그 task의 alias (예: vision 미설정 → insight)
    4. 다 비면 → Nest에 등록된 enabled 모델 중 첫 모델 자동 선택
    """
    if override:
        return override
    a = task_alias(task_key)
    if a:
        return a
    if fallback_key:
        a = task_alias(fallback_key)
        if a:
            return a
    return llm.default_alias(prefer_vision=prefer_vision)


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


from agent import personas   # 베르/쿠키 페르소나 — 어드민(/admin)에서 수정


AUDIO_SYSTEM = """당신은 오디오에서 소리를 인식하는 보조입니다.
- 들리는 소리를 종류별로 묘사하세요(말소리·음악·환경음·기계음 등).
- 사람 말이 있으면 들리는 그대로 한국어로 전사하고, 화자 구분이 가능하면 표시.
- 음악이면 분위기·장르·악기를, 환경음이면 장소·상황을 추정.
- 사실 묘사 위주. 의견·해석은 다음 단계 LLM의 몫. 한국어 2~5문장."""


def _prepare(
    user_comment: Optional[str],
    images: Optional[List[Any]],   # [(bytes, ext), ...] — 여러 장 가능
    model: Optional[str],
    audio_bytes: Optional[bytes],
    audio_ext: str,
    video_bytes: Optional[bytes],
    video_ext: str,
    backfill: bool = False,        # 지나간 사진 — EXIF 촬영시각을 캡처 ts로
    companion_prompt: Optional[str] = None,   # 동반자 선제 멘트 — 이 기록이 그 답일 때
    companion_speaker: Optional[str] = None,  # 베르 | 쿠키 (멘트 화자)
) -> Dict[str, Any]:
    """검증 + 미디어 저장 + EXIF — LLM 없이 빠르게 끝나는 부분. ctx 반환."""
    images = images or []
    if not user_comment and not images and not audio_bytes and not video_bytes:
        raise ValueError("comment·image·audio·video 중 하나 이상 필요")

    now = datetime.now()
    # 첫 사진 EXIF (저장 전 bytes에서) — 백필이면 촬영시각을 캡처 ts로 삼는다.
    exif: Dict[str, Any] = _exif_meta(images[0][0]) if images else {}
    ts = now
    if backfill and exif.get("datetime"):
        cap = _exif_dt_to_datetime(exif["datetime"])
        if cap:
            ts = cap
    record_id = f"rec-{ts.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    abs_paths: List[str] = []
    for i, (img_bytes, img_ext) in enumerate(images, start=1):
        abs_paths.append(corpus.save_image(ts, i, img_bytes, img_ext))
    audio_abs: List[str] = []
    if audio_bytes:
        audio_abs.append(corpus.save_audio(ts, 1, audio_bytes, audio_ext))
    video_abs: List[str] = []
    if video_bytes:
        video_abs.append(corpus.save_video(ts, 1, video_bytes, video_ext))

    return {
        "ts": ts,
        "uploaded_at": now,            # 올린 시점 (백필이면 ts < uploaded_at)
        "backfill": backfill,
        "record_id": record_id,
        "user_comment": user_comment or "",
        "model": model,
        "abs_paths": abs_paths,
        "image_paths": [corpus.to_vault_rel(p) for p in abs_paths],
        "audio_abs": audio_abs,
        "audio_paths": [corpus.to_vault_rel(p) for p in audio_abs],
        "video_abs": video_abs,
        "video_paths": [corpus.to_vault_rel(p) for p in video_abs],
        "exif": exif,
        "location": exif.get("gps"),   # 하위호환 — 기존 record.location
        "companion_prompt": (companion_prompt or "").strip() or None,
        "companion_speaker": (companion_speaker or "").strip() or None,
    }


def _process_capture(ctx: Dict[str, Any], do_append: bool = True) -> Dict[str, Any]:
    """캡션·인사이트 LLM 호출 + vault append — 동기/비동기 공용 본처리.

    do_append=False면 vault append를 건너뛴다(재처리 — 정본은 append-only로 보존,
    Mongo record만 갱신).
    """
    ts: datetime = ctx["ts"]
    user_comment: str = ctx["user_comment"]
    abs_paths: List[str] = ctx["abs_paths"]
    audio_abs: List[str] = ctx["audio_abs"]
    # EXIF 힌트 — 촬영시각·위치·기기를 분석/코멘트가 시각 근거로 쓰게 한 덩어리로.
    _exif = ctx.get("exif") or {}
    _eh: List[str] = []
    if _exif.get("datetime"):
        _eh.append(f"촬영시각 {_exif['datetime']}")
    if _exif.get("gps"):
        _eh.append(f"GPS {_exif['gps']}")
    if _exif.get("device"):
        _eh.append(f"기기 {_exif['device']}")
    location_hint = f"\n[사진 EXIF: {', '.join(_eh)}]" if _eh else ""

    # 사진 첨부 → Nest용 이미지 (사진 3단계 vision에서 사용)
    nest_images = nest_client.images_from_paths(abs_paths) if abs_paths else None

    # 소리 인식 — 명시된 오디오 모델(TASK_ALIAS['audio'])이 있을 때만.
    # 아무 모델(claude 등)에 오디오를 보내면 안 되므로 default/폰 model 폴백을 쓰지 않는다.
    audio_caption = ""
    audio_alias: Optional[str] = task_alias("audio") or None
    if audio_abs and audio_alias:
        try:
            r = llm.call(
                audio_alias,
                ("이 오디오에서 들리는 소리를 묘사하고, 말이 있으면 그대로 전사해주세요."
                 + location_hint),
                audio=nest_client.audio_from_paths(audio_abs),
                system=AUDIO_SYSTEM,
            )
            audio_caption = (r.get("text") or "").strip()
        except Exception as e:
            audio_caption = f"(소리 인식 실패: {e})"
    # audio_alias 없으면 저장만 (audio_caption 빈 문자열)

    # 인사이트 — 사진이면 3단계(분석→코멘트→제안), 아니면 텍스트/오디오 단일.
    # 백필(지난 사진)은 맥락 없이 — 지금 흐름에 억지로 엮지 않게 working_memory 미주입.
    backfill = bool(ctx.get("backfill"))
    context_block = "" if backfill else memory_mod.working_memory(ts)
    # 사진은 vision task(미설정 시 insight 폴백), 텍스트·소리는 insight.
    if abs_paths:
        insight_alias = _resolve_alias("vision", ctx.get("model"),
                                       prefer_vision=True, fallback_key="insight")
    else:
        insight_alias = _resolve_alias("insight", ctx.get("model"), prefer_vision=False)
    vlm_alias: Optional[str] = None
    vlm_caption = ""
    analysis: Optional[Dict[str, Any]] = None
    suggestion = ""
    insight_text = ""

    if not insight_alias:
        insight_text = "(insight alias 미설정 — Nest에 enabled 모델 없음)"
        insight_alias = ""

    # 동반자 선제 멘트의 '답'인 기록 — 그 맥락을 LLM에만 전달(user_comment는 깨끗이 둠).
    # 흐름엔 그 멘트가 별도 버블로 이미 떠 있으니, 여기선 답에 자연스럽게 반응만 하게.
    _comp = (ctx.get("companion_prompt") or "").strip()
    _comp_who = (ctx.get("companion_speaker") or "").strip() or "동반자"
    companion_note = (
        f"[방금 {_comp_who}가 아빠에게 먼저 \"{_comp}\"라고 말을 걸었고, 지금 이 기록은 "
        f"아빠가 그 말에 답하는 거야. 그 흐름을 알고 자연스럽게 이어 반응해줘.]"
        if _comp else "")

    # 이번 입력(코멘트 + 소리 + GPS) 한 덩어리
    _ui: List[str] = []
    if user_comment:
        _ui.append(f"코멘트: {user_comment}")
    if audio_caption:
        _ui.append(f"소리: {audio_caption}")
    user_input = " / ".join(_ui) + location_hint
    if backfill:
        user_input = ("[지난 사진을 뒤늦게 올린 것 — 지금 흐름·맥락과 무관하니 과거 기록을 "
                      "끌어오지 말고, 보이는 것만 간결히 한두 마디로.]\n" + user_input)
    elif companion_note:
        user_input = companion_note + "\n" + user_input

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
            _maybe_ledger_receipt(ctx, insight_alias, nest_images, analysis, vlm_caption)
        except Exception as e:
            insight_text = f"(인사이트 생성 실패: {e})"
    elif insight_alias and not (user_comment or audio_caption):
        # 영상-only / 소리 인식 미설정 오디오-only — LLM에 줄 텍스트가 없다.
        # "(빈 입력)"으로 호출하면 비용만 들고 환각성 코멘트가 정본 vault에 남음 → 저장만.
        insight_text = "(미디어 저장됨 — 코멘트·소리 인식이 없어 즉답은 생략)"
    elif insight_alias:
        # 텍스트/오디오만 — 단일 인사이트
        prompt_parts: List[str] = []
        if companion_note:
            prompt_parts.append(companion_note)
        if user_comment:
            prompt_parts.append(f"[유저 코멘트]\n{user_comment}")
        if audio_caption:
            prompt_parts.append(f"[소리]\n{audio_caption}")
        insight_prompt = "\n\n".join(prompt_parts) + location_hint
        if context_block:
            insight_prompt = (
                f"[최근 맥락·기억 — 지난 며칠 일기 + 오늘 흐름, 참고만]\n{context_block}\n\n"
                f"---\n\n[지금 입력]\n{insight_prompt}"
            )
        try:
            r = llm.call(insight_alias, insight_prompt, system=personas.insight_system())
            insight_text = (r.get("text") or "").strip()
        except Exception as e:
            insight_text = f"(인사이트 생성 실패: {e})"

    # Vault 평문 append (정본) — LLM 응답까지 전부 평문화
    #    (vault 마크다운 안에선 절대→상대 변환됨 — append_record가 처리)
    if do_append:
        anchor = corpus.append_record(
            ts=ts,
            record_id=ctx["record_id"],
            user_comment=user_comment,
            image_paths=abs_paths,
            vlm_caption=vlm_caption,
            insight_text=insight_text,
            suggestion=suggestion,
            audio_paths=audio_abs,
            audio_caption=audio_caption,
            video_paths=ctx["video_abs"],
        )
        vault_path = f"{corpus.day_vault_path(ts)}#{anchor}"
    else:
        vault_path = ctx.get("vault_path", "")   # 재처리 — 기존 정본 위치 유지

    return {
        "vault_path": vault_path,
        "vlm": {"alias": vlm_alias, "caption": vlm_caption} if vlm_alias else None,
        "analysis": analysis,
        "audio": {"alias": audio_alias, "caption": audio_caption} if audio_alias else None,
        "insight": {"alias": insight_alias, "text": insight_text},
        "suggestion": suggestion or None,
    }


def _quick_react(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """쿠키(오목눈이) 빠른 1차 반응 — 한마디. 미설정/실패면 None.

    메인 디스커버리(베르) 전에 먼저 호출돼 record.quick에 들어간다.
    영상·음성이 끼면 멀티모달(quick_av), 아니면 텍스트/사진(quick).
    """
    abs_paths = ctx.get("abs_paths") or []
    audio_abs = ctx.get("audio_abs") or []
    video_abs = ctx.get("video_abs") or []
    has_av = bool(audio_abs or video_abs)
    alias = (task_alias("quick_av") if has_av else task_alias("quick")) or ""
    if not alias:
        return None
    from agent import quick as quick_mod
    media: List[Dict[str, str]] = []
    if abs_paths:
        media += nest_client.images_from_paths(abs_paths)
    if audio_abs:
        media += nest_client.audio_from_paths(audio_abs)
    if video_abs:
        media += nest_client.video_from_paths(video_abs)
    # 쿠키 1차 반응은 '오늘 흐름'만 — 지난 며칠 서술 일기(분량 크고 옛 시간대 많음)는 빼서
    # 캡처 대신 맥락에 쏠리지 않게. 베르(insight)는 working_memory(일기 포함) 그대로.
    # (백필=지난 사진은 맥락 미주입 — 베르와 같은 규칙.)
    context = "" if ctx.get("backfill") else memory_mod.today_flow(ctx.get("ts"))
    try:
        text = quick_mod.say(alias, user_input=ctx.get("user_comment") or "",
                             media=media or None, context=context)
        return {"alias": alias, "text": text} if text else None
    except Exception as e:
        print(f"[quick] 쿠키 반응 실패: {e}", flush=True)
        return None


# 영수증 같은 사진만 가계부 추출(매 사진마다 추가 LLM 호출 안 하게 게이트)
_RECEIPT_HINT = re.compile(r"영수증|receipt|합계|총액|거래\s*내역|결제\s*내역|카드\s*전표|승인번호")


def _maybe_ledger_receipt(ctx: Dict[str, Any], alias: str, images, analysis, caption: str) -> None:
    """사진이 영수증 같으면 비전으로 추출해 가계부로(merge). 아니면 조용히 통과."""
    if not images or not alias:
        return
    blob = (caption or "") + " " + json.dumps(analysis or {}, ensure_ascii=False)
    if not _RECEIPT_HINT.search(blob):
        return
    from agent import vision
    f = vision.extract_receipt(alias, images)
    if not (isinstance(f, dict) and f.get("is_receipt") and f.get("total")):
        return
    import ledger as ledger_mod
    res = ledger_mod.from_receipt(ctx["record_id"], ctx.get("ts"), {
        "amount": f.get("total"), "merchant": f.get("merchant"),
        "items": f.get("items"), "date": f.get("date"), "method": f.get("method"),
        "image": (ctx.get("image_paths") or [None])[0],   # 기록 사진 — 가계부서 열람
    })
    print(f"[ingest] 영수증→가계부({res}): {f.get('merchant')} {f.get('total')}원", flush=True)


def _maybe_save_pending_place(ctx: Dict[str, Any]) -> None:
    """askplace('여기 어디?') 직후 짧은 텍스트 답이면 그 곳을 임시 장소로 저장(스펙: 답하면 저장).

    오저장 방지: 텍스트만(사진·소리 X) + 짧음(장소 이름급 ≤30자) + pending이 최근(15분)일 때만.
    """
    try:
        comment = (ctx.get("user_comment") or "").strip()
        if not comment or len(comment) > 30:
            return
        if ctx.get("image_paths") or ctx.get("audio_paths") or ctx.get("video_paths"):
            return
        pp = db.settings().find_one({"_id": "pending_place"})
        if not pp or pp.get("lat") is None:
            return
        from datetime import datetime, timedelta
        ts = pp.get("ts")
        if not isinstance(ts, datetime) or (datetime.now() - ts) > timedelta(minutes=15):
            return
        import places as places_mod
        places_mod.upsert(name=comment, lat=pp.get("lat"), lng=pp.get("lng"),
                          kind="place", description="(자동 등록 — '여기 어디?' 답)")
        db.settings().delete_one({"_id": "pending_place"})
        print(f"[place] 임시 장소 저장: {comment}", flush=True)
    except Exception as e:
        print(f"[place] pending 저장 실패: {e}", flush=True)


def _record_doc(ctx: Dict[str, Any], body: Dict[str, Any], status: str) -> Dict[str, Any]:
    """ctx + 처리 결과 → MongoDB record 문서."""
    return {
        "_id": ctx["record_id"],
        "ts": ctx["ts"],                        # 백필이면 EXIF 촬영시각
        "uploaded_at": ctx.get("uploaded_at"),  # 올린 시점 (백필 표시·정렬용)
        "backfill": bool(ctx.get("backfill")),  # 지나간 사진 여부
        "status": status,                       # processing | done | failed
        "vault_path": body.get("vault_path", ""),
        "image_paths": ctx["image_paths"],
        "audio_paths": ctx["audio_paths"],
        "video_paths": ctx["video_paths"],
        "user_comment": ctx["user_comment"],
        "exif": ctx.get("exif") or {},          # 촬영시각·GPS·기기·방향
        "location": ctx.get("location"),        # "lat,lon" 문자열 또는 None
        "quick": body.get("quick"),             # 쿠키 빠른 1차 {alias, text} 또는 None
        "vlm": body.get("vlm"),
        "analysis": body.get("analysis"),       # 사진 3단계 1단계 JSON
        "audio": body.get("audio"),
        "insight": body.get("insight") or {"alias": "", "text": ""},
        "suggestion": body.get("suggestion"),   # 디스커버리 제안 (베르)
        # 동반자 선제 멘트의 답이면 그 멘트 — 흐름엔 별도 버블, 여긴 연결 기록(맥락)
        "companion": ({"speaker": ctx.get("companion_speaker"),
                       "prompt": ctx.get("companion_prompt")}
                      if ctx.get("companion_prompt") else None),
        "reaction": None,                       # legacy 단일 (구앱 호환)
        "reactions": {},                        # 섹션별: analysis|comment|discovery
        # 자정 배치가 부착할 것들 — 시작은 null/빈리스트
        "type_hint": None,
        "tags": [],
        "thread_ids": [],
    }


def _response(ctx: Dict[str, Any], body: Dict[str, Any], status: str) -> Dict[str, Any]:
    """앱 응답 shape — 동기/비동기 공통."""
    return {
        "record_id": ctx["record_id"],
        "ts": ctx["ts"].isoformat(),
        "uploaded_at": ctx["uploaded_at"].isoformat() if ctx.get("uploaded_at") else None,
        "backfill": bool(ctx.get("backfill")),
        "status": status,
        "quick": body.get("quick"),          # 쿠키 빠른 반응 (stub이면 None)
        "insight": ((body.get("insight") or {}).get("text")) or "",
        "suggestion": body.get("suggestion") or "",
        "analysis": body.get("analysis"),
        "vlm_caption": ((body.get("vlm") or {}).get("caption")) or "",
        "audio_caption": ((body.get("audio") or {}).get("caption")) or "",
        "vault_path": body.get("vault_path", ""),
        "image_paths": ctx["image_paths"],   # vault-relative
        "audio_paths": ctx["audio_paths"],
        "video_paths": ctx["video_paths"],
    }


def ingest(
    user_comment: Optional[str] = None,
    images: Optional[List[Any]] = None,   # [(bytes, ext), ...] — 여러 장 가능
    model: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    audio_ext: str = "m4a",
    video_bytes: Optional[bytes] = None,
    video_ext: str = "mp4",
    backfill: bool = False,
    companion_prompt: Optional[str] = None,
    companion_speaker: Optional[str] = None,
) -> Dict[str, Any]:
    """캡처 한 건 동기 인입 — LLM까지 완료 후 완성 Record 반환 (구버전 앱 호환).

    model: Nest alias(예: 'claude', 'codex', 'gemini', 'qwen-vlm', 'trio').
           None이면 TASK_ALIAS 디폴트 사용. 사용자가 폰 UI에서 선택한 값이 들어옴.
    backfill: 지나간 사진 — EXIF 촬영시각을 ts로, 즉답은 맥락 없이 간결.
    companion_prompt: 동반자 선제 멘트의 답이면 그 멘트 — 즉답이 맥락을 알고 반응하게.
    """
    ctx = _prepare(user_comment, images, model,
                   audio_bytes, audio_ext, video_bytes, video_ext, backfill=backfill,
                   companion_prompt=companion_prompt, companion_speaker=companion_speaker)
    body = _process_capture(ctx)
    body["quick"] = _quick_react(ctx)        # 쿠키 한마디 (동기 경로 — 구앱 호환)
    db.records().insert_one(_record_doc(ctx, body, "done"))
    _maybe_save_pending_place(ctx)           # '여기 어디?' 답이면 임시 장소 저장
    return _response(ctx, body, "done")


def ingest_async_start(
    user_comment: Optional[str] = None,
    images: Optional[List[Any]] = None,   # [(bytes, ext), ...] — 여러 장 가능
    model: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    audio_ext: str = "m4a",
    video_bytes: Optional[bytes] = None,
    video_ext: str = "mp4",
    backfill: bool = False,
    companion_prompt: Optional[str] = None,
    companion_speaker: Optional[str] = None,
):
    """비동기 인입 1단계 — 미디어 저장 + stub record 즉시 생성.

    반환: (응답 dict, finish용 ctx). 라우터가 ctx로 ingest_async_finish를
    BackgroundTasks에 건다. stub은 목록/단건 조회에 바로 보인다(status=processing).
    backfill: 지나간 사진 — EXIF 촬영시각을 ts로, 즉답은 맥락 없이 간결.
    companion_prompt: 동반자 선제 멘트의 답이면 그 멘트 — 즉답이 맥락을 알고 반응하게.
    """
    ctx = _prepare(user_comment, images, model,
                   audio_bytes, audio_ext, video_bytes, video_ext, backfill=backfill,
                   companion_prompt=companion_prompt, companion_speaker=companion_speaker)
    db.records().insert_one(_record_doc(ctx, {}, "processing"))
    _maybe_save_pending_place(ctx)           # '여기 어디?' 답이면 임시 장소 저장
    return _response(ctx, {}, "processing"), ctx


def ingest_async_finish(ctx: Dict[str, Any]) -> None:
    """비동기 인입 2단계 — LLM 처리 + vault append + record 완성 + 임베딩.

    응답이 나간 뒤 threadpool에서 실행. 실패해도 record는 status=failed로 남아
    앱 폴링이 멈추고, 미디어는 이미 vault에 저장돼 있다.
    """
    record_id = ctx["record_id"]
    # 1) 쿠키 빠른 반응 먼저 (haiku ~3초) — 폰 폴링이 베르보다 먼저 본다.
    quick = _quick_react(ctx)
    if quick:
        db.records().update_one({"_id": record_id}, {"$set": {"quick": quick}})
    # 2) 베르 디스커버리 (사진 3단계 등, 1~3분)
    try:
        body = _process_capture(ctx)
        db.records().update_one(
            {"_id": record_id},
            {"$set": {
                "status": "done",
                "vault_path": body.get("vault_path", ""),
                "vlm": body.get("vlm"),
                "analysis": body.get("analysis"),
                "audio": body.get("audio"),
                "insight": body.get("insight"),
                "suggestion": body.get("suggestion"),
            }},
        )
    except Exception as e:
        print(f"[ingest] async finish 실패 ({record_id}): {e!r}", flush=True)
        db.records().update_one(
            {"_id": record_id},
            {"$set": {
                "status": "failed",
                "insight": {"alias": "", "text": f"(처리 실패: {e})"},
            }},
        )
        return
    # 검색용 임베딩 — graceful(미설정/실패 무해)
    try:
        embedding_mod.embed_record(record_id)
    except Exception:
        pass


def update_comment(record_id: str, new_comment: str) -> bool:
    """잘못 보낸 record의 user_comment 수정. vault 평문은 append-only 원칙대로 그대로 두고
    MongoDB(UI source)만 갱신."""
    res = db.records().update_one(
        {"_id": record_id},
        {"$set": {"user_comment": new_comment}},
    )
    return res.matched_count > 0


def _ctx_from_record(r: Dict[str, Any]) -> Dict[str, Any]:
    """저장된 record → _process_capture/_quick_react용 ctx 재구성 (재처리용)."""
    img_rel = r.get("image_paths") or []
    aud_rel = r.get("audio_paths") or []
    vid_rel = r.get("video_paths") or []
    return {
        "ts": r["ts"],
        "uploaded_at": r.get("uploaded_at"),
        "backfill": bool(r.get("backfill")),
        "record_id": r["_id"],
        "user_comment": r.get("user_comment") or "",
        "model": None,
        "abs_paths": [corpus.absolute_from_rel(p) for p in img_rel],
        "audio_abs": [corpus.absolute_from_rel(p) for p in aud_rel],
        "video_abs": [corpus.absolute_from_rel(p) for p in vid_rel],
        "image_paths": img_rel,
        "audio_paths": aud_rel,
        "video_paths": vid_rel,
        "exif": r.get("exif") or {},
        "location": r.get("location"),
        "vault_path": r.get("vault_path", ""),
    }


def _build_user_input(r: Dict[str, Any]) -> str:
    """record → vision용 user_input 재구성 (코멘트+소리+EXIF) — 재처리용."""
    _ui: List[str] = []
    if r.get("user_comment"):
        _ui.append(f"코멘트: {r['user_comment']}")
    ac = (r.get("audio") or {}).get("caption")
    if ac:
        _ui.append(f"소리: {ac}")
    exif = r.get("exif") or {}
    eh: List[str] = []
    if exif.get("datetime"):
        eh.append(f"촬영시각 {exif['datetime']}")
    if exif.get("gps"):
        eh.append(f"GPS {exif['gps']}")
    if exif.get("device"):
        eh.append(f"기기 {exif['device']}")
    return " / ".join(_ui) + (f"\n[사진 EXIF: {', '.join(eh)}]" if eh else "")


def _reprocess_part(ctx: Dict[str, Any], r: Dict[str, Any], part: str) -> Dict[str, Any]:
    """재처리 — 한 부분만 다시 생성 (quick·analysis·comment·discovery)."""
    if part == "quick":
        return {"quick": _quick_react(ctx)}
    abs_paths = ctx["abs_paths"]
    if not abs_paths:
        return {}   # 사진 없는 record는 analysis/comment/discovery 대상 아님
    from agent import vision
    nest_images = nest_client.images_from_paths(abs_paths)
    alias = _resolve_alias("vision", None, prefer_vision=True, fallback_key="insight")
    if not alias:
        return {}
    user_input = _build_user_input(r)
    if part == "analysis":
        analysis = vision.analyze(alias, nest_images, user_input=user_input)
        return {"analysis": analysis,
                "vlm": {"alias": alias, "caption": _summarize_analysis(analysis)}}
    if part in ("comment", "discovery"):
        analysis = r.get("analysis") or {}
        reasoning = vision.reason(alias, nest_images, analysis,
                                  user_input=user_input, context="", memory="")
        if part == "comment":
            return {"insight": {"alias": alias, "text": reasoning.get("comment") or ""}}
        return {"suggestion": reasoning.get("suggestion") or ""}
    return {}


def reprocess(record_id: str, part: str = "all") -> Optional[Dict[str, Any]]:
    """기존 record를 같은 미디어·코멘트로 다시 처리.

    part로 일부만(quick·analysis·comment·discovery) 또는 전체(all). 내용이 이상할 때
    재처리 — 그 이력을 reprocess_log에 남긴다. vault 정본은 append-only로 보존,
    Mongo record만 갱신 + 임베딩 재생성. 반환: 갱신된 record (없으면 None)."""
    r = db.records().find_one({"_id": record_id})
    if not r:
        return None
    ctx = _ctx_from_record(r)
    db.records().update_one({"_id": record_id}, {"$set": {"status": "processing"}})
    now = datetime.now()
    try:
        if part == "all":
            quick = _quick_react(ctx)
            body = _process_capture(ctx, do_append=False)
            update = {
                "quick": quick,
                "vlm": body.get("vlm"),
                "analysis": body.get("analysis"),
                "audio": body.get("audio"),
                "insight": body.get("insight"),
                "suggestion": body.get("suggestion"),
            }
        else:
            update = _reprocess_part(ctx, r, part)
    except Exception as e:
        db.records().update_one(
            {"_id": record_id},
            {"$set": {"status": "failed",
                      "insight": {"alias": "", "text": f"(재처리 실패: {e})"}}})
        return get_record(record_id)
    update["status"] = "done"
    db.records().update_one({"_id": record_id}, {
        "$set": update,
        "$push": {"reprocess_log": {"part": part, "at": now.isoformat()}},
    })
    try:
        embedding_mod.embed_record(record_id)
    except Exception:
        pass
    return get_record(record_id)


REACTION_SECTIONS = ("analysis", "comment", "discovery")


def set_reaction(record_id: str, reaction: str, section: Optional[str] = None) -> bool:
    """유저 피드백.

    section 지정(analysis|comment|discovery) → reactions.{section}에 저장,
    빈 문자열이면 해제(None). 섹션별 의미:
      analysis  = 정확도 (accurate|lacking|wrong)
      comment   = 동반자 코멘트 (good|meh|off)
      discovery = 디스커버리 가치 (interesting|known|skip)
    section 없으면 legacy 단일 reaction 필드 (구버전 앱 호환).
    """
    if section:
        if section not in REACTION_SECTIONS:
            raise ValueError(f"unknown section: {section}")
        update = {"$set": {f"reactions.{section}": (reaction or None)}}
    else:
        update = {"$set": {"reaction": reaction}}
    res = db.records().update_one({"_id": record_id}, update)
    return res.matched_count > 0


def _normalize(r: Dict[str, Any]) -> Dict[str, Any]:
    """응답 정규화: ts → ISO 문자열, image/audio_paths → vault-relative, 내부 임베딩 제거."""
    if hasattr(r.get("ts"), "isoformat"):
        r["ts"] = r["ts"].isoformat()
    if hasattr(r.get("uploaded_at"), "isoformat"):
        r["uploaded_at"] = r["uploaded_at"].isoformat()
    r["image_paths"] = [corpus.to_vault_rel(p) for p in r.get("image_paths", []) or []]
    r["audio_paths"] = [corpus.to_vault_rel(p) for p in r.get("audio_paths", []) or []]
    r["video_paths"] = [corpus.to_vault_rel(p) for p in r.get("video_paths", []) or []]
    r.pop("embedding", None)   # 내부 검색용 벡터 — 폰에 안 보냄
    r.pop("embed_meta", None)
    return r


def hide_record(record_id: str) -> bool:
    """soft delete — 흐름·검색에서 숨김(완전 삭제 X). 어드민에서는 그대로 보인다.
    실수 업로드 취소 시 쿠키 반응까지 같이 숨기는 용도."""
    res = db.records().update_one(
        {"_id": record_id},
        {"$set": {"hidden": True, "hidden_at": datetime.now()}},
    )
    return res.matched_count > 0


def list_recent(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """최근 Record N개 (채팅 무한 스크롤용) — 숨김(hidden) 제외."""
    cur = (
        db.records()
        .find({"hidden": {"$ne": True}})
        .sort("ts", -1)
        .skip(offset)
        .limit(limit)
    )
    return [_normalize(r) for r in cur]


def get_record(record_id: str) -> Optional[Dict[str, Any]]:
    r = db.records().find_one({"_id": record_id})
    return _normalize(r) if r else None
