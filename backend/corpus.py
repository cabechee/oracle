"""정본 vault 관리 — 날짜별 마크다운 + 이미지.

append-only 평문. 정본의 핵심 속성:
- 사람이 grep/git/Obsidian으로 직접 읽기 가능
- MongoDB가 손실돼도 여기서 재생성
- LLM이 그날 다 읽기 좋게 한 파일에 하루치 (자정 다이제스트의 입력)
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from config import VAULT_DIR


def _day_path(ts: datetime) -> Path:
    """corpus/YYYY/MM/DD.md."""
    return Path(VAULT_DIR) / f"{ts.year:04d}/{ts.month:02d}/{ts.day:02d}.md"


def _images_dir(ts: datetime) -> Path:
    return Path(VAULT_DIR) / "images" / f"{ts.year:04d}/{ts.month:02d}"


def _media_name(ts: datetime, idx: int, ext: str) -> str:
    """미디어 파일명 — 초 단위 ts에 uuid 꼬리를 붙여 같은 초 동시 인입의 덮어쓰기 방지
    (전송이 fire-and-forget이라 동시 ingest 가능, record_id와 같은 이유)."""
    return f"{ts.day:02d}-{ts.strftime('%H%M%S')}-{idx}-{uuid.uuid4().hex[:6]}.{ext}"


def _bake_orientation(content: bytes) -> bytes:
    """JPEG의 EXIF Orientation을 픽셀에 굽기 — LLM 전송 직전 정규화 용도.

    카메라 직촬 JPEG은 센서 방향 픽셀 + Orientation 태그로 오는데, LLM 경로(b64)는
    태그를 적용하지 않아 모델이 누운 사진을 본다(vision 분석에 "90도 회전" 반복).
    정본은 원본 그대로 저장(사용자 결정 2026-06-11) — 변환은 전송 페이로드에만.
    나머지 EXIF(GPS 등)는 보존. 비JPEG·정방향·PIL 부재·실패 시 원본 그대로(graceful).
    """
    try:
        import io
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(content)) as im:
            if im.format != "JPEG" or im.getexif().get(0x0112, 1) == 1:
                return content
            baked = ImageOps.exif_transpose(im)
            buf = io.BytesIO()
            kw = {"exif": baked.info["exif"]} if baked.info.get("exif") else {}
            baked.save(buf, "JPEG", quality=92, **kw)
            return buf.getvalue()
    except Exception:
        return content


def save_image(ts: datetime, idx: int, content: bytes, ext: str = "jpg") -> str:
    """이미지 저장 → 절대경로 반환 (Nest /api/call이 절대경로 요구). 원본 그대로."""
    d = _images_dir(ts)
    d.mkdir(parents=True, exist_ok=True)
    p = d / _media_name(ts, idx, ext)
    p.write_bytes(content)
    return str(p.resolve())


def _audio_dir(ts: datetime) -> Path:
    return Path(VAULT_DIR) / "audio" / f"{ts.year:04d}/{ts.month:02d}"


def save_audio(ts: datetime, idx: int, content: bytes, ext: str = "m4a") -> str:
    """오디오 저장 → 절대경로 반환 (Nest /api/call이 절대경로 요구)."""
    d = _audio_dir(ts)
    d.mkdir(parents=True, exist_ok=True)
    p = d / _media_name(ts, idx, ext)
    p.write_bytes(content)
    return str(p.resolve())


def _video_dir(ts: datetime) -> Path:
    return Path(VAULT_DIR) / "video" / f"{ts.year:04d}/{ts.month:02d}"


def save_video(ts: datetime, idx: int, content: bytes, ext: str = "mp4") -> str:
    """영상 저장 → 절대경로 반환."""
    d = _video_dir(ts)
    d.mkdir(parents=True, exist_ok=True)
    p = d / _media_name(ts, idx, ext)
    p.write_bytes(content)
    return str(p.resolve())


def append_record(
    *,
    ts: datetime,
    record_id: str,
    user_comment: str,
    image_paths: List[str],
    vlm_caption: str,
    insight_text: str,
    suggestion: str = "",
    audio_paths: List[str] = None,
    audio_caption: str = "",
    video_paths: List[str] = None,
) -> str:
    """vault 마크다운에 한 Record append. 반환: anchor 문자열(HHMM)."""
    path = _day_path(ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    anchor = ts.strftime("%H%M")
    is_new = not path.exists()

    parts: List[str] = []
    if is_new:
        parts.append(f"# {ts.strftime('%Y-%m-%d')}\n")

    # 헤더: ## HH:MM  (이미지·오디오가 있으면 Obsidian wiki-link로 inline 임베드)
    parts.append(f"\n## {ts.strftime('%H:%M')}")
    for att in list(image_paths) + list(audio_paths or []) + list(video_paths or []):
        try:
            rel = os.path.relpath(att, VAULT_DIR)
        except ValueError:
            rel = att
        parts.append(f" ![[{rel}]]")
    parts.append("\n")

    if user_comment:
        parts.append(f"**유저**: {user_comment}\n")
    if audio_caption:
        parts.append(f"**소리**: {audio_caption}\n")
    if vlm_caption:
        parts.append(f"**분석**: {vlm_caption}\n")
    if insight_text:
        parts.append(f"**코멘트**: {insight_text}\n")
    if suggestion:
        parts.append(f"**제안**: {suggestion}\n")
    parts.append(f"<!-- {record_id} -->\n")

    with open(path, "a", encoding="utf-8") as f:
        f.write("".join(parts))

    return anchor


def day_vault_path(ts: datetime) -> str:
    """vault 기준 상대경로 (예: '2026/06/01.md') — Record.vault_path에 저장."""
    p = _day_path(ts)
    return str(p.relative_to(VAULT_DIR))


def to_vault_rel(path: str) -> str:
    """절대경로/상대경로 어느 것이든 vault 기준 상대경로로 정규화.
    vault 밖이거나 변환 실패 시 원본 그대로 반환 (legacy 데이터 안전).
    """
    if not path:
        return path
    try:
        rel = os.path.relpath(path, VAULT_DIR)
        if rel.startswith(".."):
            return path
        return rel
    except ValueError:
        return path


def absolute_from_rel(rel_or_abs: str) -> str:
    """vault-relative 경로를 절대경로로. 이미 절대면 그대로."""
    if os.path.isabs(rel_or_abs):
        return rel_or_abs
    return str((Path(VAULT_DIR) / rel_or_abs).resolve())


def read_day(ts: datetime) -> str:
    """그날 vault 파일 전체 본문 (자정 다이제스트 입력용). 없으면 빈 문자열."""
    p = _day_path(ts)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")
