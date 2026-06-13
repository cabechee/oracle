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


def test_bake_orientation_rotates_pixels_and_keeps_gps():
    """EXIF Orientation=6 JPEG → 픽셀 회전(가로↔세로) + 태그 제거 + GPS 보존."""
    pytest = __import__("pytest")
    Image = pytest.importorskip("PIL.Image")
    import io
    for mod in ("config", "corpus"):
        sys.modules.pop(mod, None)
    import corpus

    # 1280x720 가로 픽셀 + Orientation 6 (= 시계방향 90도 돌려 보라) + GPS
    im = Image.new("RGB", (1280, 720), (200, 100, 50))
    exif = Image.Exif()
    exif[0x0112] = 6                                   # Orientation
    exif[0x8825] = {1: "N", 2: ((37, 1), (30, 1), (0, 1)),
                    3: "E", 4: ((127, 1), (0, 1), (0, 1))}  # GPSInfo IFD
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())

    baked = corpus._bake_orientation(buf.getvalue())
    out = Image.open(io.BytesIO(baked))
    assert out.size == (720, 1280)                     # 세로로 굽힘
    assert out.getexif().get(0x0112, 1) == 1           # 태그 소거(또는 정방향)
    assert out.getexif().get_ifd(0x8825)               # GPS 살아있음


def test_bake_orientation_passthrough_when_upright_or_not_jpeg():
    pytest = __import__("pytest")
    pytest.importorskip("PIL.Image")
    for mod in ("config", "corpus"):
        sys.modules.pop(mod, None)
    import corpus

    assert corpus._bake_orientation(b"not an image") == b"not an image"
