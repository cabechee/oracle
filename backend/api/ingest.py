"""인입 라우터 — POST /ingest + LLM alias 목록(폰 UI 채우기용)."""

from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks

import ingest as ingest_mod
import nest_client
import embedding as embedding_mod

router = APIRouter()


@router.post("/ingest")
def ep_ingest(
    background_tasks: BackgroundTasks,
    file: Optional[List[UploadFile]] = File(None),   # 사진 — 'file' 필드 1~N개(여러 장 캡처)
    audio: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    comment: Optional[str] = Form(None),
    model: Optional[str] = Form(None),    # Nest alias — 폰 UI에서 선택
    async_mode: Optional[str] = Form(None),   # "1"이면 비동기 — stub 즉시 반환+백그라운드 처리
    backfill: Optional[str] = Form(None),     # "1"이면 지나간 사진 — EXIF 촬영시각을 ts로
):
    """캡처 인입 — 사진(file, 여러 장 가능)·오디오·코멘트 중 하나 이상.

    'file' 필드를 여러 번 보내면 한 record에 여러 사진이 묶인다(구앱은 1개 → 호환).
    model 비어있으면 TASK_ALIAS 디폴트. async_mode 없으면 동기(구앱 호환).
    """
    images: List = []                       # [(bytes, ext), ...]
    for f in (file or []):
        b = f.file.read()
        if not b:
            continue
        ext = "jpg"
        if f.filename and "." in f.filename:
            e = f.filename.rsplit(".", 1)[-1].lower()
            if e in ("jpg", "jpeg", "png", "webp", "heic"):
                ext = "jpg" if e == "jpeg" else e
        images.append((b, ext))

    audio_bytes: Optional[bytes] = None
    audio_ext = "m4a"
    if audio is not None:
        audio_bytes = audio.file.read()
        if audio.filename and "." in audio.filename:
            aext = audio.filename.rsplit(".", 1)[-1].lower()
            if aext in ("m4a", "mp3", "wav", "aac", "ogg", "webm", "flac"):
                audio_ext = aext

    video_bytes: Optional[bytes] = None
    video_ext = "mp4"
    if video is not None:
        video_bytes = video.file.read()
        if video.filename and "." in video.filename:
            vext = video.filename.rsplit(".", 1)[-1].lower()
            if vext in ("mp4", "mov", "webm", "mkv", "avi", "m4v", "3gp"):
                video_ext = vext

    if not images and not comment and not audio_bytes and not video_bytes:
        raise HTTPException(400, "file·audio·video·comment 중 하나 이상 필요")

    is_backfill = backfill in ("1", "true", "yes")

    if async_mode in ("1", "true", "yes"):
        # 비동기: 미디어 저장 + stub record 즉시 반환, LLM·vault·임베딩은 응답 후
        try:
            result, ctx = ingest_mod.ingest_async_start(
                comment, images, model=model,
                audio_bytes=audio_bytes, audio_ext=audio_ext,
                video_bytes=video_bytes, video_ext=video_ext, backfill=is_backfill)
        except Exception as e:
            raise HTTPException(500, str(e))
        background_tasks.add_task(ingest_mod.ingest_async_finish, ctx)
        return result

    try:
        result = ingest_mod.ingest(comment, images, model=model,
                                   audio_bytes=audio_bytes, audio_ext=audio_ext,
                                   video_bytes=video_bytes, video_ext=video_ext,
                                   backfill=is_backfill)
    except Exception as e:
        raise HTTPException(500, str(e))
    # 검색용 임베딩은 응답 후 백그라운드 — 즉답 지연 방지, graceful(미설정/실패 무해)
    background_tasks.add_task(embedding_mod.embed_record, result["record_id"])
    return result


@router.get("/llm/models")
def ep_llm_models():
    """Nest 등록 모델 + council alias. 토큰은 backend에만 — 폰에 노출 X."""
    try:
        return {
            "models": nest_client.list_models(),
            "councils": nest_client.list_councils(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))
