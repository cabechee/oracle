"""tracks — 원시 동선 점. 시각 변환 + ts/좌표 멱등(DB는 fake)."""

from datetime import datetime

import tracks


def test_to_dt_forms():
    assert isinstance(tracks._to_dt(1718000000000), datetime)        # epoch ms
    assert tracks._to_dt("2026-06-28T10:00:00").hour == 10           # ISO
    assert isinstance(tracks._to_dt(None), datetime)                 # graceful
    assert isinstance(tracks._to_dt("nope"), datetime)              # graceful


class _FakeTracks:
    def __init__(self):
        self.docs = {}

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = doc


def test_record_idempotent(monkeypatch):
    fake = _FakeTracks()
    monkeypatch.setattr(tracks.db, "tracks", lambda: fake)
    ts = 1718000000000
    id1 = tracks.record(37.5, 127.0, ts=ts, acc=12.0, source="x", moving=True)
    id2 = tracks.record(37.5, 127.0, ts=ts, acc=99.0, source="y", moving=False)
    assert id1 == id2                       # 같은 ts+좌표 = 같은 _id(멱등)
    assert len(fake.docs) == 1
    assert fake.docs[id1]["moving"] is False    # 마지막 값으로 덮어씀
    assert fake.docs[id1]["lat"] == 37.5


def test_record_optional_fields_omitted(monkeypatch):
    fake = _FakeTracks()
    monkeypatch.setattr(tracks.db, "tracks", lambda: fake)
    tid = tracks.record(37.5, 127.0, ts=1718000000000)
    doc = fake.docs[tid]
    assert "acc" not in doc and "source" not in doc and "moving" not in doc
