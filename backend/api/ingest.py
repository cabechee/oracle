"""인입 라우터 — POST /ingest + LLM alias 목록(폰 UI 채우기용)."""

from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks

import ingest as ingest_mod
import nest_client
import embedding as embedding_mod

router = APIRouter()


@router.post("/ingest")
def ep_ingest(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    video: Optional[UploadFile] = File(None),
    comment: Optional[str] = Form(None),
    model: Optional[str] = Form(None),   # Nest alias — 폰 UI에서 선택
):
    """캡처 인입 — 사진(file)·오디오(audio)·코멘트(comment) 중 하나 이상.

    model 비어있으면 TASK_ALIAS 디폴트 사용.
    """
    image_bytes: Optional[bytes] = None
    image_ext = "jpg"
    if file is not None:
        image_bytes = file.file.read()
        if file.filename and "." in file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext in ("jpg", "jpeg", "png", "webp", "heic"):
                image_ext = "jpg" if ext == "jpeg" else ext

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

    if not image_bytes and not comment and not audio_bytes and not video_bytes:
        raise HTTPException(400, "file·audio·video·comment 중 하나 이상 필요")

    try:
        result = ingest_mod.ingest(comment, image_bytes, image_ext, model=model,
                                   audio_bytes=audio_bytes, audio_ext=audio_ext,
                                   video_bytes=video_bytes, video_ext=video_ext)
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
