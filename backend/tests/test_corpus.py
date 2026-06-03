"""corpus 모듈 단위 테스트 — vault read/append + 경로 정규화."""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_to_vault_rel_relative_for_inside_path():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VAULT_DIR"] = tmp
        for mod in ("config", "corpus"):
            sys.modules.pop(mod, None)
        import corpus

        abs_path = os.path.join(tmp, "images", "2026", "06", "01-1230-1.jpg")
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        Path(abs_path).write_bytes(b"fake")
        rel = corpus.to_vault_rel(abs_path)
        assert rel == "images/2026/06/01-1230-1.jpg", rel


def test_to_vault_rel_passthrough_for_outside_path():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VAULT_DIR"] = tmp
        for mod in ("config", "corpus"):
            sys.modules.pop(mod, None)
        import corpus

        outside = "/tmp/some/other/place.jpg"
        rel = corpus.to_vault_rel(outside)
        assert rel == outside


def test_append_record_creates_day_file():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VAULT_DIR"] = tmp
        for mod in ("config", "corpus"):
            sys.modules.pop(mod, None)
        import corpus

        ts = datetime(2026, 6, 1, 14, 23, 45)
        anchor = corpus.append_record(
            ts=ts,
            record_id="rec-test-001",
            user_comment="테스트 comment",
            image_paths=[],
            vlm_caption="",
            insight_text="LLM 응답 본문",
        )
        assert anchor == "1423"
        md_path = Path(tmp) / "2026" / "06" / "01.md"
        assert md_path.exists()
        body = md_path.read_text(encoding="utf-8")
        assert "# 2026-06-01" in body
        assert "## 14:23" in body
        assert "테스트 comment" in body
        assert "LLM 응답 본문" in body
        assert "<!-- rec-test-001 -->" in body
