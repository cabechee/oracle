"""정본 vault 관리 — 날짜별 마크다운 + 이미지.

append-only 평문. 정본의 핵심 속성:
- 사람이 grep/git/Obsidian으로 직접 읽기 가능
- MongoDB가 손실돼도 여기서 재생성
- LLM이 그날 다 읽기 좋게 한 파일에 하루치 (자정 다이제스트의 입력)
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List

from config import VAULT_DIR


def _day_path(ts: datetime) -> Path:
    """corpus/YYYY/MM/DD.md."""
    return Path(VAULT_DIR) / f"{ts.year:04d}/{ts.month:02d}/{ts.day:02d}.md"


def _images_dir(ts: datetime) -> Path:
    return Path(VAULT_DIR) / "images" / f"{ts.year:04d}/{ts.month:02d}"


def save_image(ts: datetime, idx: int, content: bytes, ext: str = "jpg") -> str:
    """이미지 저장 → 절대경로 반환 (Nest /api/call이 절대경로 요구)."""
    d = _images_dir(ts)
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{ts.day:02d}-{ts.strftime('%H%M%S')}-{idx}.{ext}"
    p = d / fname
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
) -> str:
    """vault 마크다운에 한 Record append. 반환: anchor 문자열(HHMM)."""
    path = _day_path(ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    anchor = ts.strftime("%H%M")
    is_new = not path.exists()

    parts: List[str] = []
    if is_new:
        parts.append(f"# {ts.strftime('%Y-%m-%d')}\n")

    # 헤더: ## HH:MM  (이미지가 있으면 Obsidian wiki-link로 inline)
    parts.append(f"\n## {ts.strftime('%H:%M')}")
    for img in image_paths:
        try:
            rel = os.path.relpath(img, VAULT_DIR)
        except ValueError:
            rel = img
        parts.append(f" ![[{rel}]]")
    parts.append("\n")

    if user_comment:
        parts.append(f"**유저**: {user_comment}\n")
    if vlm_caption:
        parts.append(f"**VLM**: {vlm_caption}\n")
    if insight_text:
        parts.append(f"**LLM**: {insight_text}\n")
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
