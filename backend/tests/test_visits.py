"""visits 단위 테스트 — 시각 변환·장소명 (DB 불요 순수 부분)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import visits  # noqa: E402


def test_to_dt_handles_forms():
    assert isinstance(visits._to_dt(1718000000000), datetime)        # epoch ms
    assert visits._to_dt("2026-06-15T10:00:00").hour == 10           # ISO
    assert isinstance(visits._to_dt(None), datetime)                 # graceful
    assert isinstance(visits._to_dt("not-a-date"), datetime)         # graceful


def test_place_name():
    assert visits._place_name({"place": "home"}) == "집"
    assert visits._place_name({"place": "office"}) == "작업실"
    assert visits._place_name({"place": None, "label": "단골 카페"}) == "단골 카페"
    assert visits._place_name({"place": None}) == "어떤 곳"
